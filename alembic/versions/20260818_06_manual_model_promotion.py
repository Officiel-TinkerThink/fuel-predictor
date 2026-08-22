"""add manual model promotion lifecycle

Revision ID: 20260818_06
Revises: 20260818_05
Create Date: 2026-08-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_06"
down_revision: str | None = "20260818_05"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("lifecycle_status", sa.String(length=16), nullable=False, server_default="candidate"),
    )
    op.add_column("model_versions", sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE model_versions SET lifecycle_status = 'active', promoted_at = trained_at "
        "WHERE version = (SELECT MAX(version) FROM model_versions)"
    )
    op.create_index(
        "ux_model_versions_one_active",
        "model_versions",
        ["lifecycle_status"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'active'"),
        sqlite_where=sa.text("lifecycle_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ux_model_versions_one_active", table_name="model_versions")
    op.drop_column("model_versions", "retired_at")
    op.drop_column("model_versions", "promoted_at")
    op.drop_column("model_versions", "lifecycle_status")
