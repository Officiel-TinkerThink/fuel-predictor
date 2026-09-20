"""Turning a spoken vehicle or stop name into the catalog's spelling.

A planner talking to an agent says "truck crane 01" and "SP II"; the catalogs
hold "Truck Crane 01" and "SP-II". The resolution has to bridge that, and when
it cannot, name what it nearly matched so the agent can ask instead of guess.
"""

import pytest

from fuel_predictor.application.catalog_resolution import (
    UnknownLocationError,
    UnknownVehicleError,
    resolve_location,
    resolve_vehicle,
    search_locations,
)
from fuel_predictor.application.locations import LocationOption
from fuel_predictor.application.vehicles import VehicleLineage, VehicleOption, lineage_from


class _Vehicles:
    def __init__(self, *options: VehicleOption) -> None:
        self._options = options

    def options(self) -> tuple[VehicleOption, ...]:
        return self._options

    def find(self, name: str) -> VehicleOption | None:
        wanted = name.strip().casefold().replace(" ", "")
        for option in self._options:
            spellings = (option.name, *option.aliases)
            if wanted in {spelling.casefold().replace(" ", "") for spelling in spellings}:
                return option
        return None

    def lineage_of(self, name: str | None) -> VehicleLineage:
        return lineage_from(self.find(name) if name else None)


class _Locations:
    def __init__(self, *names: str) -> None:
        self._options = tuple(LocationOption(name, 0.0, 0.0) for name in names)

    def options(self) -> tuple[LocationOption, ...]:
        return self._options

    def find(self, name: str) -> LocationOption | None:
        for option in self._options:
            if option.name.casefold() == name.strip().casefold():
                return option
        return None


_FLEET = _Vehicles(
    VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
    VehicleOption("Truck Crane 02", "Crane", ("T CRANE 02",)),
    VehicleOption("Prime Mover", "Truck", ("PM 01",)),
)
_STOPS = _Locations("POOL LIMAU", "SP-II", "SP-III", "YARD LIMAU", "Laboratorium Limau Field")


@pytest.mark.parametrize("written", ["Truck Crane 01", "truck crane 01", "T CRANE 01", "tcrane01"])
def test_a_vehicle_resolves_from_its_name_or_alias_regardless_of_case_and_spacing(
    written: str,
) -> None:
    assert resolve_vehicle(_FLEET, written).name == "Truck Crane 01"


def test_a_vehicle_resolves_through_punctuation_the_catalog_does_not_use() -> None:
    assert resolve_vehicle(_FLEET, "truck-crane-01").name == "Truck Crane 01"


def test_an_unknown_vehicle_names_its_nearest_candidates_rather_than_picking_one() -> None:
    with pytest.raises(UnknownVehicleError) as raised:
        resolve_vehicle(_FLEET, "truck crane")

    assert raised.value.candidates == ("Truck Crane 01", "Truck Crane 02")
    assert "Kandidat terdekat: Truck Crane 01, Truck Crane 02" in str(raised.value)
    assert "list_vehicles" in str(raised.value)


@pytest.mark.parametrize("written", ["SP-II", "sp-ii", "SP II", "sp ii", "SPII", "SP 2", "sp2"])
def test_a_stop_resolves_through_hyphens_spaces_and_numeral_style(written: str) -> None:
    """The catalog numbers its stations in roman numerals; speech uses digits."""
    assert resolve_location(_STOPS, written).name == "SP-II"


def test_a_name_the_catalog_lists_twice_is_ambiguous_rather_than_a_coin_toss() -> None:
    stops = _Locations("WORKSHOP RAM", "Workshop RAM")

    with pytest.raises(UnknownLocationError) as raised:
        resolve_location(stops, "workshop-ram")

    assert raised.value.ambiguous is True
    assert raised.value.candidates == ("WORKSHOP RAM", "Workshop RAM")
    assert "ambigu" in str(raised.value)


def test_a_stop_is_never_resolved_by_partial_match() -> None:
    """ "Limau" is three different places; picking one would route to it."""
    with pytest.raises(UnknownLocationError) as raised:
        resolve_location(_STOPS, "limau")

    assert set(raised.value.candidates) == {
        "POOL LIMAU",
        "YARD LIMAU",
        "Laboratorium Limau Field",
    }
    assert "search_locations" in str(raised.value)


def test_searching_locations_puts_the_tightest_match_first() -> None:
    assert [option.name for option in search_locations(_STOPS, "sp")] == ["SP-II", "SP-III"]
    assert [option.name for option in search_locations(_STOPS, "sp ii")] == ["SP-II"]


def test_searching_locations_respects_the_limit_and_ignores_empty_queries() -> None:
    assert len(search_locations(_STOPS, "limau", limit=2)) == 2
    assert search_locations(_STOPS, "  ") == ()
