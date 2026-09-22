"""Who planned each operation and who reported each actual, and when it was planned.

Until now neither carried an author, so there was nothing to show an
administrator about a person's work. Nullable: rows from before this
revision, and programs that identify themselves no further, have no name to
give.

Revision ID: 20260922_26
Revises: 20260922_25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_26"
down_revision: str | None = "20260922_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("daily_operations") as batch:
        batch.add_column(sa.Column("created_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_daily_operations_created_by", ["created_by"])
    with op.batch_alter_table("actual_fuel_records") as batch:
        batch.add_column(sa.Column("recorded_by", sa.String(128), nullable=True))
        batch.create_index("ix_actual_fuel_records_recorded_by", ["recorded_by"])


def downgrade() -> None:
    with op.batch_alter_table("actual_fuel_records") as batch:
        batch.drop_index("ix_actual_fuel_records_recorded_by")
        batch.drop_column("recorded_by")
    with op.batch_alter_table("daily_operations") as batch:
        batch.drop_index("ix_daily_operations_created_by")
        batch.drop_column("created_at")
        batch.drop_column("created_by")
