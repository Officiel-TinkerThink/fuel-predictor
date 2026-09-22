"""One way to page, sort and search every list.

Every list page used to show everything it had, in one order, with at most
a client-side filter. `listing.paginate` gives them all the same behaviour
from the same four URL parameters - cari (search), urut (sort key), arah
(direction), hal (page), per (page size) - so a person who learns one page
knows them all, and a bookmark or a shared link reproduces the same view.
"""

from dataclasses import dataclass

from fuel_predictor.delivery.listing import ListingQuery, SortOption, paginate


@dataclass(frozen=True)
class _Row:
    name: str
    size: int


_ROWS = [
    _Row(name, size)
    for name, size in (("delta", 4), ("alpha", 1), ("charlie", 3), ("bravo", 2), ("echo", 5))
]
_SORTS = (
    SortOption("name", "Nama", lambda row: row.name),
    SortOption("size", "Ukuran", lambda row: row.size),
)


def _query(**params: str) -> ListingQuery:
    return ListingQuery.from_params(params)


def test_defaults_to_the_first_page_in_the_default_order() -> None:
    listing = paginate(
        _ROWS,
        _query(),
        search=lambda row: [row.name],
        sorts=_SORTS,
        default_sort="size",
        default_direction="desc",
        per_page=2,
    )

    assert [row.name for row in listing.items] == ["echo", "delta"]
    assert (listing.page, listing.pages, listing.total) == (1, 3, 5)
    assert listing.first_index == 1 and listing.last_index == 2


def test_search_is_case_insensitive_and_narrows_the_total() -> None:
    listing = paginate(
        _ROWS, _query(cari="AL"), search=lambda row: [row.name], sorts=_SORTS, default_sort="name"
    )

    assert [row.name for row in listing.items] == ["alpha"]
    assert listing.total == 1 and listing.q == "AL"


def test_sort_key_and_direction_come_from_the_url_and_bad_values_fall_back() -> None:
    by_name = paginate(
        _ROWS,
        _query(urut="name", arah="asc"),
        search=lambda row: [row.name],
        sorts=_SORTS,
        default_sort="size",
    )
    bad = paginate(
        _ROWS,
        _query(urut="nope", arah="sideways", hal="99", per="0"),
        search=lambda row: [row.name],
        sorts=_SORTS,
        default_sort="size",
    )

    assert [row.name for row in by_name.items][:2] == ["alpha", "bravo"]
    assert bad.sort == "size" and bad.direction == "desc"
    # A page past the end is the last page; a nonsense size is the default.
    assert bad.page == bad.pages == 1 and bad.per_page == 20


def test_page_links_keep_the_other_parameters() -> None:
    listing = paginate(
        _ROWS,
        _query(cari="a", urut="name", arah="asc"),
        search=lambda row: [row.name],
        sorts=_SORTS,
        default_sort="size",
        per_page=2,
    )

    assert listing.total == 4  # delta, alpha, charlie, bravo
    assert listing.pages == 2
    assert listing.url(page=2) == "?cari=a&urut=name&arah=asc&per=2&hal=2"
    assert listing.url(sort="size", direction="desc") == "?cari=a&urut=size&arah=desc&per=2"


def test_only_the_offered_page_sizes_are_accepted() -> None:
    listing = paginate(
        _ROWS, _query(per="50"), search=lambda row: [row.name], sorts=_SORTS, default_sort="size"
    )
    odd = paginate(
        _ROWS, _query(per="7"), search=lambda row: [row.name], sorts=_SORTS, default_sort="size"
    )

    assert listing.per_page == 50 and odd.per_page == 20
