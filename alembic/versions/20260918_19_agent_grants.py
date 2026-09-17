"""OAuth grants for agents (ADR 0014).

A user signing in from Claude Code, Cursor or a Claude.ai connector delegates
part of their access to that program instead of pasting an administrator-issued
credential. Three tables carry the flow: the program registers itself
(`agent_registrations`), the user's consent travels as a short-lived code
(`agent_authorization_codes`), and the resulting delegation with its access and
refresh tokens is the grant (`agent_grants`).

Only hashes of codes and tokens are stored, as with `agent_clients` and
`user_sessions`. `agent_clients` is untouched: static credentials remain for
headless agents.

Revision ID: 20260918_19
Revises: 20260905_18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_19"
down_revision: str | None = "20260905_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_registrations",
        sa.Column("registration_id", sa.String(40), primary_key=True),
        sa.Column("client_name", sa.String(128), nullable=False),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "registration_id",
            sa.String(40),
            sa.ForeignKey("agent_registrations.registration_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(40),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("redirect_uri", sa.String(1024), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "agent_grants",
        sa.Column("grant_id", sa.String(40), primary_key=True),
        sa.Column(
            "registration_id",
            sa.String(40),
            sa.ForeignKey("agent_registrations.registration_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(40),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_refresh_token_hash", sa.String(64), nullable=True),
        sa.UniqueConstraint("access_token_hash"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_agent_grants_registration_id", "agent_grants", ["registration_id"])
    op.create_index("ix_agent_grants_user_id", "agent_grants", ["user_id"])
    op.create_index(
        "ix_agent_grants_access_token_hash", "agent_grants", ["access_token_hash"], unique=True
    )
    op.create_index(
        "ix_agent_grants_refresh_token_hash", "agent_grants", ["refresh_token_hash"], unique=True
    )
    op.create_index(
        "ix_agent_grants_previous_refresh_token_hash",
        "agent_grants",
        ["previous_refresh_token_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_grants_previous_refresh_token_hash", table_name="agent_grants")
    op.drop_index("ix_agent_grants_refresh_token_hash", table_name="agent_grants")
    op.drop_index("ix_agent_grants_access_token_hash", table_name="agent_grants")
    op.drop_index("ix_agent_grants_user_id", table_name="agent_grants")
    op.drop_index("ix_agent_grants_registration_id", table_name="agent_grants")
    op.drop_table("agent_grants")
    op.drop_table("agent_authorization_codes")
    op.drop_table("agent_registrations")
