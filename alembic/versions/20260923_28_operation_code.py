"""Give every planned operation an operation code (ADR 0016).

The code - `260923-0914-VT01` - is what an operator writes down when a
prediction is made and types back to record the actual fuel. New operations
get one when they are created; this backfills the operations already stored,
so the ones still waiting for actual fuel can be recorded by code as well.

Imported history has no creation time and is never waiting for actual fuel, so
it keeps an empty code. A unique index rather than a constraint: both databases
let any number of rows leave it null.

The code rule is copied here on purpose instead of imported: a migration must
keep producing what it produced on the day it shipped, whatever the
application's rule becomes later.

Revision ID: 20260923_28
Revises: 20260922_27
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op
from fuel_predictor.configuration import ApplicationSettings

revision: str = "20260923_28"
down_revision: str | None = "20260922_27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_daily_operations_operation_code"

_operations = sa.table(
    "daily_operations",
    sa.column("operation_id", sa.String()),
    sa.column("operation_code", sa.String()),
    sa.column("vehicle", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.add_column(
        "daily_operations", sa.Column("operation_code", sa.String(length=40), nullable=True)
    )
    _backfill()
    op.create_index(_INDEX, "daily_operations", ["operation_code"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="daily_operations")
    with op.batch_alter_table("daily_operations") as batch:
        batch.drop_column("operation_code")


def _backfill() -> None:
    # The same setting, read the same way (environment, then .env) as the
    # application that will form new codes after this runs.
    zone = ZoneInfo(ApplicationSettings().site_timezone)
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(_operations.c.operation_id, _operations.c.vehicle, _operations.c.created_at)
        .where(_operations.c.created_at.is_not(None))
        # Oldest first, so the first operation in a minute keeps the bare code.
        .order_by(_operations.c.created_at, _operations.c.operation_id)
    ).all()
    taken: set[str] = set()
    for operation_id, vehicle, created_at in rows:
        code = _free(_base(_as_utc(created_at).astimezone(zone), vehicle), taken)
        taken.add(code)
        connection.execute(
            _operations.update()
            .where(_operations.c.operation_id == operation_id)
            .values(operation_code=code)
        )


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _base(created_at_site_time: datetime, vehicle: str | None) -> str:
    stamp = created_at_site_time.strftime("%y%m%d-%H%M")
    words = (vehicle or "").split()
    parts = [
        word
        if word.isupper() or len(word) <= 2 or any(character.isdigit() for character in word)
        else word[:1]
        for word in words
    ]
    mark = re.sub(r"[^A-Z0-9]", "", "".join(parts).upper())[:16]
    return f"{stamp}-{mark}" if mark else stamp


def _free(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"
