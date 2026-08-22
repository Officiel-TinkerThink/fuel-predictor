"""record every model package validation verdict

Revision ID: 20260822_09
Revises: 20260822_08
Create Date: 2026-08-22 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_09"
down_revision: str | None = "20260822_08"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_package_validations",
        sa.Column("validation_id", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        # Nullable on purpose: a package rejected before its manifest could be
        # parsed has no manifest to store, and that rejection is still worth
        # recording.
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("validation_id"),
    )
    op.create_index(
        "ix_model_package_validations_model_version",
        "model_package_validations",
        ["model_version"],
        unique=False,
    )
    op.create_index(
        "ix_model_package_validations_validated_at",
        "model_package_validations",
        ["validated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_package_validations_validated_at", table_name="model_package_validations"
    )
    op.drop_index(
        "ix_model_package_validations_model_version", table_name="model_package_validations"
    )
    op.drop_table("model_package_validations")
