"""What the app refuses, it refuses plainly - and nothing is half-saved.

The happy paths were well covered; these are the everyday mistakes a person
makes on the same screens: a zero or a word where litres go, a code that
does not exist, a file that is empty, a plan uploaded before any model is
active. Each is answered with a message on the page, never a crash, and
leaves nothing behind.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline
from tests.test_two_roles import _ADMIN, _sign_in


def _count(tmp_path: Path, table: str) -> int:
    url = f"sqlite+pysqlite:///{(tmp_path / 'operations.sqlite3').as_posix()}"
    with create_engine(url).connect() as db:
        count: int = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    return count


@pytest.mark.parametrize("litres", ["0", "-5", "banyak", ""])
def test_the_form_refuses_litres_that_are_not_a_positive_number(
    tmp_path: Path, litres: str
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        code = _operation_with_prediction(client, 24)["operation"]["operation_code"]
        page = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": code,
                "actual_fuel_liters": litres,
                "measurement_source": "fuel_meter",
            },
        )

    assert page.status_code == 422
    assert 'id="error-actual_fuel_liters"' in page.text
    # What was typed survives, so only the litres need retyping.
    assert f'value="{code}"' in page.text
    assert _count(tmp_path, "actual_fuel_records") == 0


@pytest.mark.parametrize("litres", [0, -5])
def test_the_api_refuses_litres_that_are_not_positive(tmp_path: Path, litres: int) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation_id = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        response = client.post(
            f"/api/v1/daily-operations/{operation_id}/actual-fuel",
            json={"actual_fuel_liters": litres, "measurement_source": "fuel_meter"},
        )

    assert response.status_code == 422
    assert _count(tmp_path, "actual_fuel_records") == 0


def test_a_sheet_row_with_zero_litres_is_named_and_the_rest_are_kept(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        good = _operation_with_prediction(client, 24)["operation"]["operation_code"]
        bad = _operation_with_prediction(client, 36)["operation"]["operation_code"]
        sheet = f"Kode Operasi (wajib),Bahan Bakar Aktual (L) (wajib)\n{good},21\n{bad},0\n"
        body = client.post(
            "/api/v1/bulk-actual-fuel",
            files={"file": ("aktual.csv", sheet.encode(), "text/csv")},
        ).json()

    assert body["accepted_row_count"] == 1
    assert body["quarantined_row_count"] == 1
    assert "lebih besar dari 0" in body["correction_report"][0]["reasons"][0]["message"]


def test_cancelling_an_operation_that_does_not_exist_says_so(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.post(
            "/operasi-harian/260101-0000-VT99/batalkan", data={"reason": "salah input"}
        )

    assert page.status_code == 404
    assert "tidak ditemukan" in page.text.lower()


def test_cancelling_without_the_form_s_token_is_refused(tmp_path: Path) -> None:
    database = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as admin:
        _sign_in(admin, *_ADMIN)
        operation_id = admin.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 20,
                "distance_source": "manual",
            },
        ).json()["operation_id"]
        refused = admin.post(
            f"/operasi-harian/{operation_id}/batalkan", data={"reason": "salah input"}
        )
        page = admin.get(f"/operasi-harian/{operation_id}").text

    assert refused.status_code == 403
    assert "Operasi dibatalkan" not in page


def test_the_slip_of_an_unknown_operation_is_not_found(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.get("/operasi-harian/260101-0000-VT99/slip")

    assert response.status_code == 404


def test_a_zero_distance_is_refused_on_the_form(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        page = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "0",
                "distance_source": "manual",
            },
        )

    assert page.status_code == 422
    assert 'id="error-total_distance_km"' in page.text
    assert _count(tmp_path, "daily_operations") == 0


def test_a_plan_uploaded_before_any_model_is_active_is_refused_whole(tmp_path: Path) -> None:
    sheet = "Kendaraan,Aktivitas (wajib),Jarak Total (km) (wajib)\nVT 01,Mobilisasi,40\n"
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.post(
            "/prediksi-operasi-massal",
            files={"file": ("rencana.csv", sheet.encode(), "text/csv")},
        )

    assert page.status_code in (409, 422)
    assert "model" in page.text.lower()
    # Nothing half-planned: no operation without its estimate.
    assert _count(tmp_path, "daily_operations") == 0


@pytest.mark.parametrize("path", ["/prediksi-operasi-massal", "/bahan-bakar-aktual-massal"])
def test_an_empty_file_is_refused_with_a_reason(tmp_path: Path, path: str) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        page = client.post(path, files={"file": ("kosong.csv", b"", "text/csv")})

    assert page.status_code == 422
    assert "kosong" in page.text.lower()


def test_an_operator_is_refused_every_administrator_action(tmp_path: Path) -> None:
    """Built from the guard's own table, so a new administrator route is
    covered the day it is added. A valid form token goes with every form
    post, so the refusal is the role's and not the token's."""
    from fuel_predictor.delivery.security import ROUTE_CAPABILITIES
    from fuel_predictor.domain.identity import UserRole, role_allows
    from tests.test_two_roles import _OPERATOR, _csrf, _sign_out

    posts = [
        path.replace("*", "X-TIDAK-ADA")
        for method, path, capability in ROUTE_CAPABILITIES
        if method == "POST" and not role_allows(UserRole.OPERATOR, capability)
    ]
    assert posts, "the table should name administrator-only actions"
    database = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database, bootstrap_administrator=_ADMIN)) as client:
        _sign_in(client, *_ADMIN)
        client.post(
            "/api/v1/users",
            json={
                "username": _OPERATOR[0],
                "full_name": "Andi",
                "password": _OPERATOR[1],
                "role": "operator",
            },
        )
        _sign_out(client)
        _sign_in(client, *_OPERATOR)
        token = _csrf(client.get("/prediksi").text)
        answers = {
            path: (
                client.post(path, json={}).status_code
                if path.startswith("/api/")
                else client.post(path, data={"csrf_token": token}).status_code
            )
            for path in posts
        }
        users = _count(tmp_path, "users")

    assert {path: code for path, code in answers.items() if code != 403} == {}
    assert users == 2
