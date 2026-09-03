"""Record what the vehicle does at each stop.

Activity used to be one value for the whole operation, which could not say that
a run loads at one stop and unloads at another. The planner now picks an
activity per stop, so it is stored beside the stop it belongs to.

Nullable: the departure point has no activity, and operations recorded before
this migration have none either.

Revision ID: 20260904_16
Revises: 20260904_15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_16"
down_revision: str | None = "20260904_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_operation_stops",
        sa.Column("activity", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_operation_stops", "activity")
