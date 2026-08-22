"""create PostgreSQL persistence tables

Revision ID: 20260818_01
Revises:
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_operations",
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("vehicle_category", sa.String(length=64), nullable=False),
        sa.Column("activity_mode", sa.String(length=64), nullable=False),
        sa.Column("lifting_hours", sa.Float(), nullable=True),
        sa.Column("total_distance_km", sa.Float(), nullable=False),
        sa.Column("distance_source", sa.String(length=64), nullable=False),
        sa.CheckConstraint("total_distance_km > 0", name="daily_operation_distance_gt_zero"),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("version", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_operation_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_row_count", sa.Integer(), nullable=False),
        sa.Column("ignored_blank_row_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("version"),
        sa.UniqueConstraint("dataset_version_id"),
    )
    op.create_table(
        "historical_daily_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.String(length=32), nullable=False),
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("vehicle_category", sa.String(length=64), nullable=False),
        sa.Column("activity_mode", sa.String(length=64), nullable=False),
        sa.Column("lifting_hours", sa.Float(), nullable=True),
        sa.Column("total_distance_km", sa.Float(), nullable=False),
        sa.Column("distance_source", sa.String(length=64), nullable=False),
        sa.Column("prepared_fuel_liters", sa.Float(), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("original_headers", sa.JSON(), nullable=False),
        sa.Column("raw_values", sa.JSON(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("total_distance_km > 0", name="historical_distance_gt_zero"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.dataset_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_daily_operations_dataset_version_id",
        "historical_daily_operations",
        ["dataset_version_id"],
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.String(length=32), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("original_headers", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("raw_values", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.dataset_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_quality_issues_dataset_version_id",
        "data_quality_issues",
        ["dataset_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_quality_issues_dataset_version_id", table_name="data_quality_issues")
    op.drop_table("data_quality_issues")
    op.drop_index(
        "ix_historical_daily_operations_dataset_version_id",
        table_name="historical_daily_operations",
    )
    op.drop_table("historical_daily_operations")
    op.drop_table("dataset_versions")
    op.drop_table("daily_operations")
