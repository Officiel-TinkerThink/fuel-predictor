"""The operation code: the handle an operator writes down when a prediction is
made, and types back weeks later to record the actual fuel.

`OPR-` plus 32 hex characters cannot be copied onto a fuel slip or read back
correctly, and says nothing about which job it was. The code says when the
operation was created, in site-local time, and which vehicle: `260924-0914-VT-P410-VT01`.
"""

from datetime import datetime

import pytest

from fuel_predictor.domain.operation_code import (
    next_free_operation_code,
    normalize_operation_reference,
    operation_code_base,
    vehicle_code,
    vehicle_mark,
)


@pytest.mark.parametrize(
    ("vehicle", "mark"),
    [
        ("VT 01", "VT01"),
        ("VT 15", "VT15"),
        ("Truck Crane 01", "TC01"),
        ("Oil Field Truck", "OFT"),
        ("Prime Mover", "PM"),
        ("Forklift SCM", "FSCM"),
        ("Wheel Loader Forklift", "WLF"),
        ("T-CRANE 02", "TCRANE02"),
        # Sheets write the unit in lower case too; it must not turn into `V01`.
        ("vt 01", "VT01"),
    ],
)
def test_the_vehicle_mark_keeps_capitals_and_numbers_and_shrinks_words_to_initials(
    vehicle: str, mark: str
) -> None:
    assert vehicle_mark(vehicle) == mark


def test_no_vehicle_means_no_mark() -> None:
    assert vehicle_mark(None) is None
    assert vehicle_mark("  ") is None


def test_the_base_is_the_site_local_minute_and_the_vehicle_code() -> None:
    created = datetime(2026, 9, 24, 9, 14, 55)

    assert operation_code_base(created, "VT-P410-VT01") == "260924-0914-VT-P410-VT01"
    assert operation_code_base(created, None) == "260924-0914"


def test_the_vehicle_code_is_group_type_unit_leaving_out_what_is_not_coded() -> None:
    assert vehicle_code("VT", "P410", "VT 01") == "VT-P410-VT01"
    assert vehicle_code("VT", "", "VT 14") == "VT-VT14"
    # A vehicle the catalog does not know: only its own mark.
    assert vehicle_code("", "", "Crane Sewa 01") == "CS01"
    assert vehicle_code("", "", None) is None


def test_a_free_base_is_used_as_is() -> None:
    assert next_free_operation_code("260923-0914-VT01", set()) == "260923-0914-VT01"


def test_a_taken_base_gets_the_lowest_free_suffix_from_two() -> None:
    taken = {"260923-0914-VT01", "260923-0914-VT01-2", "260923-0914-VT01-4"}

    assert next_free_operation_code("260923-0914-VT01", taken) == "260923-0914-VT01-3"


def test_codes_of_other_vehicles_in_the_same_minute_do_not_push_the_suffix() -> None:
    taken = {"260923-0914-VT01", "260923-0914-VT01-2"}

    assert next_free_operation_code("260923-0914", taken) == "260923-0914"


@pytest.mark.parametrize(
    "typed",
    ["260923-0914-VT01", "260923-0914-vt01", " 260923-0914-VT 01 ", "260923 - 0914 - VT01"],
)
def test_a_typed_code_is_read_ignoring_case_and_spaces(typed: str) -> None:
    assert normalize_operation_reference(typed) == "260923-0914-VT01"
