"""Index audit records by actor, for the MCP rate limiter.

The limiter counts one agent's recent tool calls on every single call, and
`audit_records` grows without bound. The existing indexes lead with `action` or
`occurred_at`, so nothing served a filter on `actor` — the query scanned the
window, and did so most often while an agent was looping, which is exactly when
it has to stay cheap.

Revision ID: 20260827_14
Revises: 20260827_13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_14"
down_revision: str | None = "20260827_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_audit_records_actor_occurred_at"


def upgrade() -> None:
    op.create_index(_INDEX, "audit_records", ["actor", "occurred_at"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="audit_records")
