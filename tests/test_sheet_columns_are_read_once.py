"""Every sheet reads its columns with one set of rules.

The plan sheet and the history sheet each carried a copy of the code that
reads an operation's columns, and the plan, history and actual-fuel sheets
each a copy of header matching and blank-row detection. They now share
`map_headers`, `is_blank_row`, `pick_columns` and `read_operation_columns`.
"""

import pytest

from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetImportError,
    OperationColumns,
    SheetRows,
    SourceSheet,
    is_blank_row,
    map_headers,
    pick_columns,
    read_operation_columns,
)
from fuel_predictor.domain.daily_operation import ActivityMode, DistanceSource, VehicleCategory
from fuel_predictor.domain.historical_dataset import CorrectionReason, RawValue

_ALIASES = {
    "activity_mode": {"aktivitas", "aktivitas wajib"},
    "total_distance_km": {"jarak total km", "jarak total km wajib"},
}


def test_headers_match_by_their_names_whatever_the_case_and_punctuation() -> None:
    mapped = map_headers(("Aktivitas (wajib)", "JARAK TOTAL (KM)", "Catatan"), _ALIASES)

    assert mapped == {"activity_mode": "Aktivitas (wajib)", "total_distance_km": "JARAK TOTAL (KM)"}


def test_the_first_of_two_matching_columns_is_the_one_read() -> None:
    mapped = map_headers(("Aktivitas", "Aktivitas (wajib)"), _ALIASES)

    assert mapped["activity_mode"] == "Aktivitas"


def test_a_row_blank_in_every_known_column_is_blank_even_with_notes_beside_it() -> None:
    mapped = {"activity_mode": "Aktivitas", "total_distance_km": "Jarak"}

    assert is_blank_row({"Aktivitas": " ", "Jarak": None, "Catatan": "libur"}, mapped)
    assert not is_blank_row({"Aktivitas": "Mobilisasi", "Jarak": None, "Catatan": ""}, mapped)
    # With no known column, only a wholly empty row is blank.
    assert not is_blank_row({"Catatan": "libur"}, {})


def test_a_missing_required_column_is_a_reason_and_an_optional_one_is_not() -> None:
    issues: list[CorrectionReason] = []

    picked = pick_columns(
        {"activity_mode": "Aktivitas"},
        {"Aktivitas": "Mobilisasi"},
        ("activity_mode", "total_distance_km", "lifting_hours"),
        {"activity_mode", "total_distance_km"},
        {"activity_mode": "Aktivitas", "total_distance_km": "Jarak total"},
        issues,
    )

    assert picked == {"activity_mode": "Mobilisasi"}
    assert issues == [CorrectionReason("total_distance_km", "Kolom Jarak total tidak ditemukan.")]


def _read(**values: RawValue) -> tuple[OperationColumns | None, list[CorrectionReason]]:
    issues: list[CorrectionReason] = []
    return read_operation_columns(values, issues), issues


def test_an_operation_needs_only_its_activity_and_distance() -> None:
    columns, issues = _read(activity_mode="Mobilisasi + lifting", total_distance_km=30.5)

    assert issues == []
    assert columns is not None
    assert columns.activity_mode is ActivityMode.TRANSPORT_AND_LIFTING
    assert columns.total_distance_km == 30.5
    # Newer sheets no longer ask for these.
    assert columns.vehicle_category is VehicleCategory.ANGBER
    assert columns.distance_source is DistanceSource.MANUAL


def test_a_distance_of_zero_is_refused_with_the_form_s_words() -> None:
    columns, issues = _read(activity_mode="Mobilisasi", total_distance_km=0)

    assert columns is None
    assert issues == [
        CorrectionReason("total_distance_km", "Jarak total harus lebih besar dari 0.")
    ]


def test_every_problem_in_a_row_is_named() -> None:
    columns, issues = _read(activity_mode="terbang", total_distance_km="jauh")

    assert columns is None
    assert [issue.field for issue in issues] == ["activity_mode", "total_distance_km"]


def test_without_an_activity_column_there_is_no_operation_but_no_second_reason() -> None:
    """The missing column was already named by `pick_columns`."""
    columns, issues = _read(total_distance_km=12)

    assert columns is None
    assert issues == []


def test_rows_are_read_from_data_sheets_with_blank_ones_counted() -> None:
    sheets = [
        # A template's instructions: no known column, not data.
        SourceSheet("Petunjuk", ("Kolom", "Arti"), ((2, ("Aktivitas", "wajib")),)),
        SourceSheet(
            "Operasi Harian",
            ("Aktivitas (wajib)", "Jarak Total (km) (wajib)"),
            ((2, ("Mobilisasi", 30)), (3, (None, " ")), (4, ("Mobilisasi", 12))),
        ),
    ]
    rows = SheetRows(_ALIASES)

    read = list(rows.read(sheets))

    assert [(row.sheet_name, row.row_number) for row in read] == [
        ("Operasi Harian", 2),
        ("Operasi Harian", 4),
    ]
    assert read[0].raw_values["Aktivitas (wajib)"] == "Mobilisasi"
    assert rows.blank_row_count == 1


def test_a_file_with_no_known_column_points_to_the_template() -> None:
    rows = SheetRows(_ALIASES)

    with pytest.raises(HistoricalDatasetImportError, match="Gunakan templat dari halaman ini"):
        list(rows.read([SourceSheet("Lain", ("Nama", "Umur"), ((2, ("Budi", 30)),))]))
