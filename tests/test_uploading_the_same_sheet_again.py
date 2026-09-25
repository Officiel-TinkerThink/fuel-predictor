"""The waiting sheet can be filled over the week and uploaded again.

That is what the sheet is for, and what the pages say - yet every upload
after the first reported each row already saved as a mistake ("sudah
tercatat"), burying the rows that really needed fixing. A row repeating the
figure on record is now counted as already recorded; only a different figure
is a problem, and the message says both numbers. The result page no longer
sends an operator to a page they may not open.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline
from tests.test_two_roles import (
    _ADMIN,
    _OPERATOR,
    _csrf,
    _sign_in,
    _train_baseline_with_csrf,
)

_HEADER = "Kode Operasi (wajib),Bahan Bakar Aktual (L) (wajib),Sumber Pengukuran (opsional)\n"


def _upload(client: TestClient, rows: list[tuple[str, str]]) -> dict[str, object]:
    sheet = _HEADER + "".join(f"{code},{litres},fuel_meter\n" for code, litres in rows)
    response = client.post(
        "/api/v1/bulk-actual-fuel",
        files={"file": ("aktual.csv", sheet.encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_the_same_sheet_uploaded_again_reports_no_mistakes(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        first = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        second = _operation_with_prediction(client, 36)["operation"]["operation_id"]

        monday = _upload(client, [(first, "21"), (second, "")])
        wednesday = _upload(client, [(first, "21"), (second, "30")])

    assert monday["accepted_row_count"] == 1 and monday["unfilled_row_count"] == 1
    assert wednesday["accepted_row_count"] == 1
    assert wednesday["already_recorded_row_count"] == 1
    assert wednesday["quarantined_row_count"] == 0


def test_a_different_figure_for_a_recorded_operation_is_named_with_both_numbers(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        _upload(client, [(operation, "21")])

        changed = _upload(client, [(operation, "25.5")])

    assert changed["accepted_row_count"] == 0
    assert changed["already_recorded_row_count"] == 0
    report = changed["correction_report"]
    assert isinstance(report, list)
    assert report[0]["reasons"][0]["message"] == (
        "Sudah tercatat 21 L, berbeda dengan 25,5 L di berkas. "
        "Angka yang sudah tercatat tidak diubah lewat impor."
    )


def test_the_form_says_the_figure_already_on_record(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        code = operation["operation_code"]
        client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": code,
                "actual_fuel_liters": "21",
                "measurement_source": "fuel_meter",
            },
        )

        same = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": code,
                "actual_fuel_liters": "21",
                "measurement_source": "fuel_meter",
            },
        )
        different = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": code,
                "actual_fuel_liters": "30",
                "measurement_source": "fuel_meter",
            },
        )

    assert same.status_code == 409 and different.status_code == 409
    assert "Sudah tercatat dengan angka yang sama (21 L)" in same.text
    assert "Operasi ini sudah tercatat 21 L." in different.text


def test_the_result_page_speaks_plainly_and_links_only_where_an_operator_may_go(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as admin:
        _sign_in(admin, *_ADMIN)
        admin.post(
            "/api/v1/users",
            json={
                "username": _OPERATOR[0],
                "full_name": "Andi",
                "password": _OPERATOR[1],
                "role": "operator",
            },
        )
        _train_baseline_with_csrf(admin)
        operation = _operation_with_prediction(admin, 24)["operation"]
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as client:
        _sign_in(client, *_OPERATOR)
        sheet = _HEADER + f"{operation['operation_code']},21,fuel_meter\nTIDAK-ADA,5,fuel_meter\n"
        page = client.post(
            "/bahan-bakar-aktual-massal",
            data={"csrf_token": _csrf(client.get("/bahan-bakar-aktual-massal").text)},
            files={"file": ("aktual.csv", sheet.encode(), "text/csv")},
        )

    main = page.text.split("<main ", 1)[1]
    assert "1 BBM aktual tersimpan." in main
    assert "1 baris perlu diperbaiki" in main
    assert "Kode operasi tidak ditemukan." in main
    assert "dikarantina" not in main and "spreadsheet_import" not in main
    assert "0 baris" not in main
    assert 'href="/pemantauan/kinerja-model"' not in main
