"""Catat Aktual says what is wrong with every field at once, in plain words.

An empty form was answered with one message, "Bahan bakar aktual harus
berupa angka." - the missing code went unmentioned until the second try,
and a blank box is not a number that failed to parse. Zero litres was
"tidak valid", which does not say what would be.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _submit(client: TestClient, code: str, liters: str) -> tuple[int, str]:
    response = client.post(
        "/bahan-bakar-aktual",
        data={"operation_id": code, "actual_fuel_liters": liters},
    )
    return response.status_code, response.text


def test_an_empty_form_names_both_missing_fields(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        status, page = _submit(client, "", "")

    assert status == 422
    assert "Kode operasi wajib diisi." in page
    assert "Bahan bakar aktual wajib diisi." in page
    assert "harus berupa angka" not in page
    assert 'href="#field-operation_id"' in page
    assert 'href="#field-actual_fuel_liters"' in page


def test_a_missing_code_is_not_reported_as_an_unknown_one(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        status, page = _submit(client, "   ", "20")

    assert status == 422
    assert "Kode operasi wajib diisi." in page
    assert "tidak ditemukan" not in page


def test_zero_litres_says_what_is_allowed(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        code = _operation_with_prediction(client, 24)["operation"]["operation_code"]
        status, page = _submit(client, code, "0")

    assert status == 422
    assert "Bahan bakar aktual harus lebih besar dari 0." in page
    # The code typed stays in the box, so only the litres need retyping.
    assert f'value="{code}"' in page


def test_letters_for_litres_are_still_called_not_a_number(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        status, page = _submit(client, "260101-0000-VT-VT01", "dua puluh")

    assert status == 422
    assert "Bahan bakar aktual harus berupa angka." in page


def test_a_complete_form_is_recorded(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        code = _operation_with_prediction(client, 24)["operation"]["operation_code"]
        status, page = _submit(client, code, "21.5")

    assert status == 201, page
    assert "21,5 L" in page


def test_the_api_names_fields_as_the_form_does(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        code = _operation_with_prediction(client, 24)["operation"]["operation_code"]
        refused = client.post(
            f"/api/v1/daily-operations/{code}/actual-fuel",
            json={"actual_fuel_liters": 20, "measurement_source": "timbangan"},
        )

    assert refused.status_code == 422
    assert "Diukur dengan tidak valid." in refused.text
