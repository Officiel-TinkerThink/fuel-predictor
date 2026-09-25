"""A list sorts by time even when some times carry a zone and some do not.

SQLite hands stored times back without a zone; one row written with its
zone kept (by hand, or by an older version) made Riwayat Prediksi answer
500, since Python refuses to order the two kinds.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from fuel_predictor.delivery.listing import ListingQuery, SortOption, paginate


def test_times_with_and_without_a_zone_sort_together() -> None:
    rows = [
        SimpleNamespace(name="naive, later", at=datetime(2026, 9, 25, 12, 0)),
        SimpleNamespace(name="aware, earlier", at=datetime(2026, 9, 25, 9, 0, tzinfo=UTC)),
        SimpleNamespace(name="no time", at=None),
    ]
    sorts = (SortOption("waktu", "Waktu", lambda row: row.at),)

    newest_first = paginate(
        rows,
        ListingQuery.from_params({}),
        search=lambda row: [row.name],
        sorts=sorts,
        default_sort="waktu",
    )
    oldest_first = paginate(
        rows,
        ListingQuery.from_params({"urut": "waktu", "arah": "asc"}),
        search=lambda row: [row.name],
        sorts=sorts,
        default_sort="waktu",
    )

    assert [row.name for row in newest_first.items] == ["naive, later", "aware, earlier", "no time"]
    assert [row.name for row in oldest_first.items] == ["aware, earlier", "naive, later", "no time"]
