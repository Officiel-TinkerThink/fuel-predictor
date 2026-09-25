"""Record when an operation was cancelled, by whom and why.

A mistaken or duplicate plan stayed "waiting for actual fuel" for good. It can
now be withdrawn before any actual fuel is recorded; these columns hold that,
and stay empty for every operation that stands.

Revision ID: 20260925_32
Revises: 20260924_31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_32"
down_revision: str | None = "20260924_31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_operations", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("daily_operations", sa.Column("cancelled_by", sa.String(128), nullable=True))
    op.add_column("daily_operations", sa.Column("cancel_reason", sa.String(256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("daily_operations") as batch:
        batch.drop_column("cancel_reason")
        batch.drop_column("cancelled_by")
        batch.drop_column("cancelled_at")
