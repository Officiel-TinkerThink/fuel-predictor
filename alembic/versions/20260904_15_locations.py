"""The location catalog, imported from the planner's "Data Lokasi" sheet.

Stop points used to be free text: whatever a planner typed went straight to the
routing provider as an address to geocode, so a typo became a silently wrong
route. The names now come from this table, and a stop that matches one is sent
to Google as its surveyed coordinates instead of a string to guess at.

Keyed by name because that is the key the source sheet already uses, and the
name is what `daily_operation_stops` records.

Revision ID: 20260904_15
Revises: 20260827_14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_15"
down_revision: str | None = "20260827_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("name", sa.String(255), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("satellite_point", sa.String(255), nullable=True),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="location_latitude_in_range"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="location_longitude_in_range"),
    )


def downgrade() -> None:
    op.drop_table("locations")
