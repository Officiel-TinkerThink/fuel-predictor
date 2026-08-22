"""add actual fuel records

Revision ID: 20260818_05
Revises: 20260818_04
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_05"
down_revision: str | None = "20260818_04"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actual_fuel_records",
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("actual_fuel_liters", sa.Float(), nullable=False),
        sa.Column("measurement_source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=True),
        sa.Column("source_sheet_name", sa.String(length=255), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.CheckConstraint("actual_fuel_liters > 0", name="actual_fuel_liters_gt_zero"),
        sa.ForeignKeyConstraint(["operation_id"], ["daily_operations.operation_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("operation_id"),
    )


def downgrade() -> None:
    op.drop_table("actual_fuel_records")
