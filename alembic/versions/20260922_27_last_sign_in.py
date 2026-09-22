"""When each account last signed in, on the account.

Successful sign-ins are no longer audit rows - they were the commonest entry
in the trail and said nothing anyone acts on. The one thing they told an
administrator, "when was this person last here", is a single value per
account and lives here now.

Revision ID: 20260922_27
Revises: 20260922_26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_27"
down_revision: str | None = "20260922_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True))
    # The last successful sign-in already in the trail seeds the column, so
    # nobody reads "Belum pernah masuk" about a colleague who was here yesterday.
    op.execute(
        sa.text(
            "UPDATE users SET last_sign_in_at = ("
            "  SELECT MAX(occurred_at) FROM audit_records"
            "  WHERE audit_records.action = 'sign_in_succeeded'"
            "  AND audit_records.subject = users.username)"
        )
    )
    # Successful sign-ins and sign-outs leave the trail; failed sign-ins stay
    # (they drive the throttle and are worth seeing).
    op.execute(
        sa.text("DELETE FROM audit_records WHERE action IN ('sign_in_succeeded', 'sign_out')")
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_sign_in_at")
