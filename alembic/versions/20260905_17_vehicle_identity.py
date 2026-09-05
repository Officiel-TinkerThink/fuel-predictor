"""Record which vehicle ran the operation, not only that it was heavy haulage.

`vehicle_category` has a single value, so as a model feature it was a constant
column carrying no information. The operational sheets have always named the
individual unit; this stores it so the model can learn that two cranes of the
same model do not consume alike.

Nullable on both tables: operations and historical rows recorded before this
migration have no unit named, and "unrecorded" is a category the model can
learn from rather than a value to invent.

Revision ID: 20260905_17
Revises: 20260904_16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_17"
down_revision: str | None = "20260904_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("daily_operations", sa.Column("vehicle", sa.String(64), nullable=True))
    op.add_column(
        "historical_daily_operations", sa.Column("vehicle", sa.String(64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("historical_daily_operations", "vehicle")
    op.drop_column("daily_operations", "vehicle")
