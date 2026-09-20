"""Resolving what a planner *said* to what the catalogs *know*.

An agent relays a vehicle or stop the way the planner spoke it — "truck crane
01", "pool limau", "SP II" — and the catalogs key on the canonical spelling
("Truck Crane 01", "POOL LIMAU", "SP-II"). The web form never had this problem
because it offers a dropdown; a conversation has no dropdown, so the lookup has
to be forgiving and, when it still fails, say what it nearly matched. Otherwise
the agent's only recourse is to guess, and a guessed stop becomes a real route.

Lives in the application layer because both the MCP adapter and, later, a
chat-style page need the same rule; putting it in the adapter would let the two
drift apart.
"""

import re
from collections.abc import Callable, Sequence

from fuel_predictor.application.locations import LocationCatalog, LocationOption
from fuel_predictor.application.vehicles import VehicleCatalog, VehicleOption

_MAX_CANDIDATES = 5


class UnknownVehicleError(LookupError):
    def __init__(self, written: str, candidates: Sequence[str], *, ambiguous: bool = False) -> None:
        self.written = written
        self.candidates = tuple(candidates)
        self.ambiguous = ambiguous
        super().__init__(
            _unknown_message("Kendaraan", written, self.candidates, "list_vehicles", ambiguous)
        )


class UnknownLocationError(LookupError):
    def __init__(self, written: str, candidates: Sequence[str], *, ambiguous: bool = False) -> None:
        self.written = written
        self.candidates = tuple(candidates)
        self.ambiguous = ambiguous
        super().__init__(
            _unknown_message(
                "Pemberhentian", written, self.candidates, "search_locations", ambiguous
            )
        )


_ROMAN = re.compile(r"^(?P<stem>[a-z]{2,}?)??(?P<numeral>(?=[ivx])x{0,3}(ix|iv|v?i{0,3}))$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10}


def normalize_name(value: str) -> str:
    """Case, spacing, punctuation and numeral style are noise in a spoken name.

    "SP II", "sp-ii", "SP-II" and "SP 2" are the same stop; so are "T CRANE 01"
    and "TCrane01". The stations are numbered in roman numerals in the catalog
    and in digits in speech, so a roman numeral standing alone or ending a word
    is read as its number before the separators are dropped. Leading zeros are
    noise too: the catalog pads to three digits ("KRG-012") and the sheets and
    the planners do not ("KRG 12", "KRG-12").
    """
    tokens = re.split(r"[^a-z0-9]+", value.casefold())
    return "".join(_unpadded(_arabic(token)) for token in tokens if token)


_PADDED = re.compile(r"^(?P<stem>[a-z]*)0+(?P<number>\d+)$")


def _unpadded(token: str) -> str:
    match = _PADDED.match(token)
    return f"{match.group('stem')}{match.group('number')}" if match else token


def _arabic(token: str) -> str:
    match = _ROMAN.match(token)
    if match is None:
        return token
    total = 0
    numeral = match.group("numeral")
    for index, char in enumerate(numeral):
        digit = _ROMAN_VALUES[char]
        following = _ROMAN_VALUES[numeral[index + 1]] if index + 1 < len(numeral) else 0
        total += -digit if digit < following else digit
    return f"{match.group('stem') or ''}{total}"


def resolve_vehicle(catalog: VehicleCatalog, written: str) -> VehicleOption:
    """The catalog's own `find` first (it already knows the aliases), then a
    punctuation-blind match. Anything looser is offered as a candidate, never
    chosen: a near-miss on a vehicle is a real operation on the wrong unit."""
    exact = catalog.find(written)
    if exact is not None:
        return exact
    wanted = normalize_name(written)
    options = catalog.options()
    matched = [option for option in options if wanted and wanted in _vehicle_keys(option)]
    if len(matched) == 1:
        return matched[0]
    if matched:
        raise UnknownVehicleError(written, [option.name for option in matched], ambiguous=True)
    raise UnknownVehicleError(
        written, [option.name for option in _closest(wanted, options, _vehicle_keys)]
    )


def resolve_location(catalog: LocationCatalog, written: str) -> LocationOption:
    exact = catalog.find(written)
    if exact is not None:
        return exact
    wanted = normalize_name(written)
    options = catalog.options()
    matched = [option for option in options if wanted and normalize_name(option.name) == wanted]
    if len(matched) == 1:
        return matched[0]
    if matched:
        # The sheet lists "WORKSHOP RAM" and "Workshop RAM" at different
        # coordinates. Choosing between them here would route to one of them
        # on a coin toss; the planner has to say which.
        raise UnknownLocationError(written, [option.name for option in matched], ambiguous=True)
    raise UnknownLocationError(
        written, [option.name for option in _closest(wanted, options, _location_keys)]
    )


def search_locations(
    catalog: LocationCatalog, query: str, limit: int = 10
) -> tuple[LocationOption, ...]:
    """Every stop whose name contains the query, shortest names first so the
    tightest match ("SP-II") precedes the ones that merely contain it ("SP-III")."""
    wanted = normalize_name(query)
    if not wanted:
        return ()
    matches = [option for option in catalog.options() if wanted in normalize_name(option.name)]
    matches.sort(key=lambda option: (len(normalize_name(option.name)), option.name))
    return tuple(matches[: max(limit, 0)])


def _vehicle_keys(option: VehicleOption) -> tuple[str, ...]:
    return tuple(normalize_name(name) for name in (option.name, *option.aliases) if name)


def _location_keys(option: LocationOption) -> tuple[str, ...]:
    return (normalize_name(option.name),)


def _closest[T](
    wanted: str,
    options: Sequence[T],
    keys_of: Callable[[T], tuple[str, ...]],
) -> list[T]:
    """Candidates for the error message: containment either way, then shared
    leading characters. Deliberately simple — the point is to let the agent ask
    "did you mean SP-II or SP-III?", not to pick for it."""
    if not wanted:
        return []
    scored: list[tuple[int, int, T]] = []
    for option in options:
        best = 0
        for key in keys_of(option):
            if not key:
                continue
            if wanted in key or key in wanted:
                score = 3
            else:
                shared = _shared_prefix_length(wanted, key)
                score = 2 if shared >= 3 else 1 if shared >= 2 else 0
            best = max(best, score)
        if best > 0:
            scored.append((-best, len(keys_of(option)[0]), option))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [option for _, _, option in scored[:_MAX_CANDIDATES]]


def _shared_prefix_length(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        count += 1
    return count


def _unknown_message(
    kind: str, written: str, candidates: Sequence[str], tool: str, ambiguous: bool
) -> str:
    if ambiguous:
        return (
            f"{kind} '{written}' ambigu: cocok dengan {', '.join(candidates)}. "
            "Sebutkan salah satunya persis seperti tertulis."
        )
    message = f"{kind} '{written}' tidak dikenal."
    if candidates:
        message += f" Kandidat terdekat: {', '.join(candidates)}."
    message += f" Gunakan alat {tool} untuk melihat pilihan yang tersedia."
    return message
