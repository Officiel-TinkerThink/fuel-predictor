"""Which vehicle taxonomy a model was trained under (ADR 0015).

A hash of the catalog's (unit, type, group) triples at training time, so that
monitoring can tell when the owner has since re-typed or re-grouped the fleet
under a model whose features depend on it. Nullable: every model trained
before this revision, and any external package that does not declare one, is
of unknown taxonomy — which is not a mismatch.

Revision ID: 20260920_21
Revises: 20260920_20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_21"
down_revision: str | None = "20260920_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("catalog_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("model_versions") as batch:
        batch.drop_column("catalog_fingerprint")
