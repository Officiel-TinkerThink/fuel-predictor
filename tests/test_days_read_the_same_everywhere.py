"""A day reads the same on every page: 25/09/2026, not 2026-09-25.

Imported history keeps its dates as the sheet had them, so the comparison
table under an estimate showed "2026-08-18" for a past day and "26/09/2026
00:12" for a recorded one, one above the other.
"""

import pytest

from fuel_predictor.delivery.rendering import format_day


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        ("2026-08-18", "18/08/2026"),
        (" 2026-08-18T07:30:00 ", "18/08/2026"),
        ("", "-"),
        (None, "-"),
        # Not a date the app can read: shown as it came, never an error.
        ("minggu lalu", "minggu lalu"),
        ("2026-13-40", "2026-13-40"),
    ],
)
def test_a_day_is_written_the_way_the_pages_write_days(written: str | None, shown: str) -> None:
    assert format_day(written) == shown
