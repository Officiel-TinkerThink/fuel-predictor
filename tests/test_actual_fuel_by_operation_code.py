"""Actual fuel is recorded against the operation code the operator wrote down.

The code is what goes on the fuel slip; weeks later it is what gets typed into
the form or the actual-fuel sheet. The `OPR-…` id keeps working everywhere the
code does, so nothing already filled in breaks.
"""

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _as_typed(code: str) -> str:
    """How a person might type it back: lower case, a stray space."""
    return f" {code.lower()} "


def test_the_api_records_actual_fuel_by_code(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]

        recorded = client.post(
            f"/api/v1/daily-operations/{operation['operation_code']}/actual-fuel",
            json={"actual_fuel_liters": 21, "measurement_source": "fuel_meter"},
        )

    assert recorded.status_code == 201, recorded.text
    # Stored against the operation itself, whichever handle was used.
    assert recorded.json()["operation_id"] == operation["operation_id"]


def test_the_form_records_actual_fuel_by_a_code_typed_loosely(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]

        saved = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": _as_typed(operation["operation_code"]),
                "actual_fuel_liters": "21",
                "measurement_source": "manual_entry",
            },
        )
        waiting = client.get("/bahan-bakar-aktual").text

    assert saved.status_code == 201, saved.text
    assert operation["operation_code"] in saved.text
    assert operation["operation_code"] not in waiting


def test_an_unknown_code_is_named_as_such(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)

        page = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": "260101-0000-VT99",
                "actual_fuel_liters": "21",
                "measurement_source": "manual_entry",
            },
        )

    assert page.status_code == 404
    assert "Kode operasi tidak ditemukan" in page.text


def test_the_sheet_takes_codes_and_old_operation_ids_alike(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        by_code = _operation_with_prediction(client, 24)["operation"]
        by_id = _operation_with_prediction(client, 36)["operation"]
        sheet = (
            "Kode Operasi (wajib),Bahan Bakar Aktual (L) (wajib),Sumber Pengukuran (opsional)\n"
            f"{_as_typed(by_code['operation_code'])},21,fuel_meter\n"
            f"{by_id['operation_id']},30,fuel_meter\n"
            "260101-0000-VT99,25,manual_entry\n"
        )

        response = client.post(
            "/api/v1/bulk-actual-fuel",
            files={"file": ("aktual.csv", sheet.encode(), "text/csv")},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert [row["actual_fuel"]["operation_id"] for row in body["accepted_rows"]] == [
        by_code["operation_id"],
        by_id["operation_id"],
    ]
    assert body["quarantined_row_count"] == 1
    assert body["correction_report"][0]["reasons"][0]["message"] == (
        "Kode operasi tidak ditemukan."
    )


def test_the_template_asks_for_the_code(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        workbook_bytes = client.get("/api/v1/bulk-actual-fuel/template?format=xlsx").content
        csv_text = client.get("/api/v1/bulk-actual-fuel/template?format=csv").text

    workbook = load_workbook(BytesIO(workbook_bytes), data_only=True)
    assert workbook["Bahan Bakar Aktual"]["A1"].value == "Kode Operasi (wajib)"
    assert csv_text.lstrip("﻿").startswith("Kode Operasi (wajib),")
