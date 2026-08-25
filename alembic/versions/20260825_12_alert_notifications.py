"""Record which alerts an operator has already been notified about.

Revision ID: 20260825_12
Revises: 20260822_11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_12"
down_revision: str | None = "20260822_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_notifications",
        sa.Column("alert_key", sa.String(length=200), primary_key=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("alert_notifications")
