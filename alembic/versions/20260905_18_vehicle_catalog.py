"""The fleet, imported from the planner's "Dim_Kendaraan" sheet.

The vehicle was a hard-coded list in application code, which meant a truck
joining or leaving the fleet needed a code change and a deploy. It is reference
data the planner already maintains in a spreadsheet, so it is stored and
imported the same way the location catalog is.

`aliases` carries the other spellings the same vehicle appears under, taken from
the workbook's own "Peta_Nama_Sumber" map: importing history that says "PM 01"
should resolve to Prime Mover rather than inventing a second vehicle.

Revision ID: 20260905_18
Revises: 20260905_17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_18"
down_revision: str | None = "20260905_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("vehicle_group", sa.String(64), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("vehicles")
