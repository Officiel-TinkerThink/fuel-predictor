"""add baseline model and prediction lineage

Revision ID: 20260818_02
Revises: 20260818_01
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_02"
down_revision: str | None = "20260818_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("version", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_version_id", sa.String(length=40), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=32), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_row_count", sa.Integer(), nullable=False),
        sa.Column("uncertainty_liters", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.dataset_version_id"]),
        sa.PrimaryKeyConstraint("version"),
        sa.UniqueConstraint("model_version_id"),
    )
    op.create_index("ix_model_versions_dataset_version_id", "model_versions", ["dataset_version_id"])
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.String(length=40), nullable=False),
        sa.Column("operation_id", sa.String(length=40), nullable=False),
        sa.Column("model_version_id", sa.String(length=40), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=32), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("estimated_fuel_requirement_liters", sa.Float(), nullable=False),
        sa.Column("recommended_allocation_liters", sa.Float(), nullable=False),
        sa.Column("uncertainty_lower_liters", sa.Float(), nullable=False),
        sa.Column("uncertainty_upper_liters", sa.Float(), nullable=False),
        sa.Column("route_distance_source", sa.String(length=64), nullable=False),
        sa.Column("safety_policy", sa.String(length=1024), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("feature_values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.model_version_id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["daily_operations.operation_id"]),
        sa.PrimaryKeyConstraint("prediction_id"),
    )
    op.create_index("ix_predictions_model_version_id", "predictions", ["model_version_id"])
    op.create_index("ix_predictions_operation_id", "predictions", ["operation_id"])


def downgrade() -> None:
    op.drop_index("ix_predictions_operation_id", table_name="predictions")
    op.drop_index("ix_predictions_model_version_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_model_versions_dataset_version_id", table_name="model_versions")
    op.drop_table("model_versions")
