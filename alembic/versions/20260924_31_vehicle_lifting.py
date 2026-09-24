"""Record which vehicles can lift.

Only a unit with lifting capacity may be planned with lifting; every other
one is mobilisation only. The flag comes from the fleet sheet like the rest of
the catalog (`bisa_lifting`), so this only adds the column, defaulting to
"cannot": `python -m fuel_predictor import-vehicles` sets it.

Revision ID: 20260924_31
Revises: 20260924_30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_31"
down_revision: str | None = "20260924_30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(
            sa.Column("can_lift", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("can_lift")
