"""add MCP agent client credentials

Revision ID: 20260822_11
Revises: 20260822_10
Create Date: 2026-08-22 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_11"
down_revision: str | None = "20260822_10"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_clients",
        sa.Column("client_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        # Only the hash is stored; a lost credential is reissued, never
        # recovered, so a database read cannot yield a working token.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_agent_clients_token_hash", "agent_clients", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_clients_token_hash", table_name="agent_clients")
    op.drop_table("agent_clients")
