"""A person's own name for an agent connection (ADR 0014).

Two connections from the same program - Claude Code on a laptop and on a
desktop - register under the same client name, so the person could not tell
them apart on Agen Saya. The label is theirs to set and clear; nothing the
client sees changes.

Revision ID: 20260921_22
Revises: 20260920_21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_22"
down_revision: str | None = "20260920_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_grants", sa.Column("label", sa.String(80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_grants") as batch:
        batch.drop_column("label")
