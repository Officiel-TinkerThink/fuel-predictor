"""Give every model version a model code; widen model ids to the package contract.

`M-260924-01`: the day the model finished training (site-local time) and its
place among that day's models. New versions get one when they are registered;
this backfills the versions already stored, in the order they were made.

The code rule is copied here instead of imported, so this migration keeps
producing what it produced on the day it shipped.

`model_versions.model_version_id` and `predictions.model_version_id` go from
40 to 64 characters: a package manifest may name its version with 64, and a
longer name validated and then failed to register. SQLite does not enforce
string lengths, and rebuilding a table other tables reference is risky there,
so the widening is done on PostgreSQL only.

Revision ID: 20260924_30
Revises: 20260924_29
"""

from collections.abc import Sequence
from datetime import UTC
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op
from fuel_predictor.configuration import ApplicationSettings

revision: str = "20260924_30"
down_revision: str | None = "20260924_29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_model_versions_model_code"

_models = sa.table(
    "model_versions",
    sa.column("version", sa.Integer()),
    sa.column("model_code", sa.String()),
    sa.column("trained_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("model_code", sa.String(length=16), nullable=True))
    _backfill()
    op.create_index(_INDEX, "model_versions", ["model_code"], unique=True)
    _set_id_length(64)


def downgrade() -> None:
    _set_id_length(40)
    op.drop_index(_INDEX, table_name="model_versions")
    with op.batch_alter_table("model_versions") as batch:
        batch.drop_column("model_code")


def _backfill() -> None:
    zone = ZoneInfo(ApplicationSettings().site_timezone)
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_models.c.version, _models.c.trained_at).order_by(_models.c.version)
    ).all()
    per_day: dict[str, int] = {}
    for version, trained_at in rows:
        moment = trained_at if trained_at.tzinfo else trained_at.replace(tzinfo=UTC)
        day = moment.astimezone(zone).strftime("%y%m%d")
        per_day[day] = per_day.get(day, 0) + 1
        connection.execute(
            _models.update()
            .where(_models.c.version == version)
            .values(model_code=f"M-{day}-{per_day[day]:02d}")
        )


def _set_id_length(length: int) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table in ("model_versions", "predictions"):
        op.alter_column(
            table,
            "model_version_id",
            type_=sa.String(length=length),
            existing_nullable=False,
        )
