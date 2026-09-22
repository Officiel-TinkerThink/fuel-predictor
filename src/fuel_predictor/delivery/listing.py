"""Paging, sorting and searching for every list page, from the same URL parameters.

`cari` searches, `urut` and `arah` sort, `hal` pages, `per` sets the page
size. The work is done in memory over the rows a page already fetched: the
lists here are hundreds of rows, not millions, and one rule that every page
follows is worth more than a query per page.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

PAGE_SIZES = (5, 10, 20, 50)
DEFAULT_PAGE_SIZE = 5


@dataclass(frozen=True, slots=True)
class SortOption:
    key: str
    label: str
    value_of: Callable[[Any], Any]
    # Where a first click on this column starts: names read best A-Z, dates
    # and amounts newest or largest first.
    default_direction: str = "desc"


@dataclass(frozen=True, slots=True)
class ListingQuery:
    q: str = ""
    sort: str | None = None
    direction: str | None = None
    page: int = 1
    per_page: int = DEFAULT_PAGE_SIZE
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_params(
        cls, params: Mapping[str, str], *, extra_keys: Iterable[str] = ()
    ) -> "ListingQuery":
        return cls(
            q=params.get("cari", "").strip(),
            sort=params.get("urut") or None,
            direction=params.get("arah") or None,
            page=_positive_int(params.get("hal"), 1),
            per_page=_page_size(params.get("per")),
            extra={key: params[key] for key in extra_keys if params.get(key)},
        )


@dataclass(frozen=True, slots=True)
class Listing:
    items: Sequence[Any]
    total: int
    page: int
    pages: int
    per_page: int
    q: str
    sort: str
    direction: str
    sorts: tuple[SortOption, ...]
    extra: dict[str, str]

    @property
    def first_index(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def last_index(self) -> int:
        return min(self.page * self.per_page, self.total)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def page_numbers(self) -> list[int]:
        """The current page with two neighbours each side, plus the ends."""
        around = {n for n in range(self.page - 2, self.page + 3) if 1 <= n <= self.pages}
        return sorted(around | {1, self.pages})

    def sort_url(self, key: str) -> str:
        """The address that sorts by this column: clicking the active column
        flips its direction, any other column starts descending for dates and
        numbers and ascending for names - whatever that option declared."""
        if key == self.sort:
            direction = "asc" if self.direction == "desc" else "desc"
        else:
            option = next((o for o in self.sorts if o.key == key), None)
            direction = option.default_direction if option else "desc"
        return self.url(sort=key, direction=direction)

    def sort_state(self, key: str) -> str:
        """The aria-sort value for this column's header."""
        if key != self.sort:
            return "none"
        return "ascending" if self.direction == "asc" else "descending"

    def url(
        self,
        *,
        page: int | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int | None = None,
    ) -> str:
        """A query string for this view with one thing changed, keeping the rest."""
        params: list[tuple[str, str]] = []
        if self.q:
            params.append(("cari", self.q))
        params.extend(self.extra.items())
        params.append(("urut", sort or self.sort))
        params.append(("arah", direction or self.direction))
        size = per_page or self.per_page
        if size != DEFAULT_PAGE_SIZE:
            params.append(("per", str(size)))
        target = page or 1
        if target > 1:
            params.append(("hal", str(target)))
        return "?" + urlencode(params)


def paginate(
    rows: Iterable[Any],
    query: ListingQuery,
    *,
    search: Callable[[Any], Iterable[str | None]],
    sorts: Sequence[SortOption],
    default_sort: str,
    default_direction: str = "desc",
    per_page: int | None = None,
) -> Listing:
    """Filter by the search text over the fields `search` names, order by the
    chosen sort option, and cut the page - all with fallbacks, so a bad URL
    shows the default view rather than an error."""
    needle = query.q.lower()
    matched = [
        row
        for row in rows
        if not needle or any(needle in (value or "").lower() for value in search(row))
    ]
    by_key = {option.key: option for option in sorts}
    sort_key = query.sort if query.sort in by_key else default_sort
    direction = query.direction if query.direction in ("asc", "desc") else default_direction
    matched.sort(key=_sortable(by_key[sort_key].value_of), reverse=direction == "desc")
    size = per_page or query.per_page
    pages = max(1, -(-len(matched) // size))
    page = min(max(query.page, 1), pages)
    start = (page - 1) * size
    return Listing(
        items=matched[start : start + size],
        total=len(matched),
        page=page,
        pages=pages,
        per_page=size,
        q=query.q,
        sort=sort_key,
        direction=direction,
        sorts=tuple(sorts),
        extra=dict(query.extra),
    )


def _sortable(value_of: Callable[[Any], Any]) -> Callable[[Any], tuple[int, Any]]:
    """None sorts last whichever way; strings compare case-insensitively."""

    def key(row: Any) -> tuple[int, Any]:
        value = value_of(row)
        if value is None:
            return (1, 0)
        if isinstance(value, str):
            return (0, value.lower())
        return (0, value)

    return key


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw or "")
    except ValueError:
        return default
    return value if value > 0 else default


def _page_size(raw: str | None) -> int:
    size = _positive_int(raw, DEFAULT_PAGE_SIZE)
    return size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
