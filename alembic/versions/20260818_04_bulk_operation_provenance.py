"""persist source provenance for bulk daily operations

Revision ID: 20260818_04
Revises: 20260818_03
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_04"
down_revision: str | None = "20260818_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_operation_sources",
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("original_headers", sa.JSON(), nullable=False),
        sa.Column("raw_values", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["daily_operations.operation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id"),
    )


def downgrade() -> None:
    op.drop_table("daily_operation_sources")
