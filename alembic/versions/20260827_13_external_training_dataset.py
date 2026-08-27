"""Stop claiming an ingested model's training dataset is one of ours.

`model_versions.dataset_version_id` was foreign-keyed to `dataset_versions`.
That holds for a model trained in this application, which imports the dataset
first. It is false for an ingested package: its manifest names a dataset in the
*builder's* environment, which need not exist here at all.

The result was a 500 on package upload against PostgreSQL — a foreign key
violation. It passed every test because SQLite does not enforce foreign keys
unless each connection opts in, so the dangling reference was silently accepted.

The column stays and keeps its value; it is provenance either way. Only the
constraint goes, because the constraint was the part asserting something untrue.

Revision ID: 20260827_13
Revises: 20260825_12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_13"
down_revision: str | None = "20260825_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "model_versions"
_COLUMN = "dataset_version_id"
_NAMED = "model_versions_dataset_version_id_fkey"


def _foreign_key_name() -> str | None:
    """The actual constraint name, which differs by dialect and may be absent.

    PostgreSQL names it; a SQLite-built schema often leaves it unnamed, and a
    database created after this migration has none at all.
    """
    for key in sa.inspect(op.get_bind()).get_foreign_keys(_TABLE):
        if _COLUMN in key.get("constrained_columns", []):
            name: str | None = key.get("name")
            return name or ""
    return None


def upgrade() -> None:
    name = _foreign_key_name()
    if name is None:
        return

    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot drop a constraint; batch mode rebuilds the table from
        # the definition given here, which simply omits the foreign key.
        with op.batch_alter_table(_TABLE, copy_from=_reflected()) as batch:
            batch.alter_column(_COLUMN, existing_type=sa.String(64), nullable=False)
        return

    op.drop_constraint(name, _TABLE, type_="foreignkey")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.create_foreign_key(_NAMED, _TABLE, "dataset_versions", [_COLUMN], ["dataset_version_id"])


def _reflected() -> sa.Table:
    """The table as it exists, minus the foreign key we are removing."""
    metadata = sa.MetaData()
    table = sa.Table(_TABLE, metadata, autoload_with=op.get_bind())
    for constraint in list(table.constraints):
        if isinstance(constraint, sa.ForeignKeyConstraint) and _COLUMN in constraint.column_keys:
            table.constraints.discard(constraint)
    for column in table.columns:
        column.foreign_keys = {
            key for key in column.foreign_keys if key.parent.name != _COLUMN
        }
    return table
