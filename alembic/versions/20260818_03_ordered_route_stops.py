"""add ordered route stops and manual fallback provenance

Revision ID: 20260818_03
Revises: 20260818_02
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_03"
down_revision: str | None = "20260818_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_operations",
        sa.Column(
            "route_distance_manual_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "daily_operation_stops",
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("stop_position", sa.Integer(), nullable=False),
        sa.Column("location_name", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["daily_operations.operation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id", "stop_position"),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "route_distance_manual_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("predictions", "route_distance_manual_fallback")
    op.drop_table("daily_operation_stops")
    op.drop_column("daily_operations", "route_distance_manual_fallback")
