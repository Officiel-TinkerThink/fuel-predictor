"""An optional email on each account, usable at sign-in in place of the username.

Nullable: a shared desk or a service account has no address to give. Stored
normalised (trimmed, lower-cased) by the application, so a plain unique index
is what keeps two accounts from sharing one.

Revision ID: 20260921_24
Revises: 20260921_23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_24"
down_revision: str | None = "20260921_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email", sa.String(254), nullable=True))
        batch.create_unique_constraint("uq_users_email", ["email"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_email", type_="unique")
        batch.drop_column("email")
