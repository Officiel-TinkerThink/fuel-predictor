"""Two roles: operator and administrator.

The manager role sat between the two with one extra menu (the audit log) and
no other reason to be a separate account type. Accounts that held it become
operators - the narrower of the two - so nobody gains access by a migration;
an administrator promotes whoever should be one.

Revision ID: 20260921_23
Revises: 20260921_22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_23"
down_revision: str | None = "20260921_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET role = 'operator' WHERE role = 'manager'"))


def downgrade() -> None:
    # The information which accounts were managers is gone; nothing to restore.
    pass
