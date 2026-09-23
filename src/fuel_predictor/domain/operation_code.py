"""The operation code: the identifier an operator writes down and types back (ADR 0016).

`260923-0914-VT01` says when the operation was created, in site-local time, and
which vehicle it was for. It is formed once, when the operation is created, and
stored; nothing here is ever used to recompute the code of an existing
operation.
"""

import re
from collections.abc import Collection
from datetime import datetime

# Long enough for any name in the catalog, short enough that a code always fits
# the column with room for a suffix.
_MAX_VEHICLE_MARK_LENGTH = 16


def vehicle_mark(vehicle: str | None) -> str | None:
    """The vehicle as a few characters: `VT 01` -> `VT01`, `Truck Crane 01` -> `TC01`.

    A word written in capitals, carrying a digit or of at most two letters is
    already short and is what people call the unit (`vt 01` is still `VT01`),
    so it is kept whole; any other word shrinks to its initial.
    """
    if vehicle is None:
        return None
    parts = [word if _kept_whole(word) else word[:1] for word in vehicle.split()]
    mark = re.sub(r"[^A-Z0-9]", "", "".join(parts).upper())
    return mark[:_MAX_VEHICLE_MARK_LENGTH] or None


def _kept_whole(word: str) -> bool:
    return word.isupper() or len(word) <= 2 or any(character.isdigit() for character in word)


def operation_code_base(created_at_site_time: datetime, vehicle: str | None) -> str:
    """The code before any suffix, from a time already in the site's time zone."""
    stamp = created_at_site_time.strftime("%y%m%d-%H%M")
    mark = vehicle_mark(vehicle)
    return f"{stamp}-{mark}" if mark else stamp


def next_free_operation_code(base: str, taken: Collection[str]) -> str:
    """The base itself, or the base with the lowest suffix from 2 nobody holds.

    The same vehicle twice in one minute is almost always a double submission;
    the second one becomes `-2` and the operator records actual fuel against one.
    """
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def normalize_operation_reference(typed: str) -> str:
    """How a code or id someone typed is compared: capitals, no spaces."""
    return re.sub(r"\s+", "", typed).upper()
