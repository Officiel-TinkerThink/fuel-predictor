"""record scheduled monitoring runs and backup outcomes

Revision ID: 20260822_10
Revises: 20260822_09
Create Date: 2026-08-22 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_10"
down_revision: str | None = "20260822_09"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitoring_runs",
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("failure_reason", sa.String(length=1024), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_monitoring_runs_finished_at", "monitoring_runs", ["finished_at"], unique=False
    )
    op.create_table(
        "backup_runs",
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("destination", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_backup_runs_finished_at", "backup_runs", ["finished_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_backup_runs_finished_at", table_name="backup_runs")
    op.drop_table("backup_runs")
    op.drop_index("ix_monitoring_runs_finished_at", table_name="monitoring_runs")
    op.drop_table("monitoring_runs")
