"""The type level of the vehicle lineage (ADR 0015).

Every unit sits in a fixed three-level lineage: the unit, its type, its
group. The type is the owner's finer cut inside a group ("VT A" among the
vacuum trucks), and a group with a single type names that type after itself —
which is every group at the time of this revision, so the column is backfilled
from `vehicle_group`. It exists now so that splitting a group later is an edit
of a few catalog cells rather than a schema change.

Revision ID: 20260920_20
Revises: 20260918_19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_20"
down_revision: str | None = "20260918_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vehicles"
_COLUMN = "vehicle_type"


def _reflected() -> sa.Table:
    # SQLite cannot alter a column in place; batch mode rebuilds the table
    # from this definition. PostgreSQL alters directly and ignores it.
    return sa.Table(
        _TABLE,
        sa.MetaData(),
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("vehicle_group", sa.String(64), nullable=False),
        sa.Column(_COLUMN, sa.String(64), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
    )


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(64), nullable=True))
    op.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = vehicle_group WHERE {_COLUMN} IS NULL"))
    with op.batch_alter_table(_TABLE, copy_from=_reflected()) as batch:
        batch.alter_column(_COLUMN, existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, copy_from=_reflected()) as batch:
        batch.drop_column(_COLUMN)
