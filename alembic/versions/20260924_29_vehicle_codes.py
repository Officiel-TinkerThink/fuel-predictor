"""Give each vehicle its group and type codes (ADR 0016).

A vehicle code reads group - type - unit, `VT-P410-VT01`, and new operation codes
carry it. The codes come from the fleet sheet like the rest of the catalog, so
this only adds the columns: `python -m fuel_predictor import-vehicles` fills
them. Until it runs they are empty, and codes name the unit alone, as before.

Revision ID: 20260924_29
Revises: 20260923_28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_29"
down_revision: str | None = "20260923_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(
            sa.Column("group_code", sa.String(length=8), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("type_code", sa.String(length=8), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("type_code")
        batch.drop_column("group_code")
