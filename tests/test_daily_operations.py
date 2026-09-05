import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


def test_api_creates_daily_operation_and_returns_generated_id(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport_and_lifting",
                "lifting_hours": 2.5,
                "total_distance_km": 86.4,
                "distance_source": "manual",
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "operation_id": response.json()["operation_id"],
        "vehicle_category": "ANGBER",
        "activity_mode": "transport_and_lifting",
        "lifting_hours": 2.5,
        "total_distance_km": 86.4,
        "distance_source": "manual",
    }
    assert response.json()["operation_id"].startswith("OPR-")


def test_api_rejects_missing_core_values_with_indonesian_feedback(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post("/api/v1/daily-operations", json={})

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {"field": "vehicle_category", "message": "Kategori kendaraan wajib diisi."},
            {"field": "activity_mode", "message": "Mode aktivitas wajib diisi."},
            {"field": "distance_source", "message": "Sumber jarak wajib diisi."},
        ]
    }


def test_api_rejects_lifting_mode_without_positive_lifting_hours(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "lifting",
                "lifting_hours": 0,
                "total_distance_km": 12,
                "distance_source": "routing_provider",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {
                "field": "lifting_hours",
                "message": "Jam lifting harus lebih besar dari 0 untuk mode yang mencakup lifting.",
            }
        ]
    }


def test_indonesian_form_creates_daily_operation_with_same_behavior(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        form = client.get("/prediksi")
        response = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport_and_lifting",
                "lifting_hours": "1.75",
                "total_distance_km": "43.2",
                "distance_source": "manual",
            },
        )

    assert form.status_code == 200
    assert "Buat Operasi Harian" in form.text
    assert response.status_code == 201
    assert "Operasi harian berhasil dibuat" in response.text
    assert "ANGBER" in response.text
    assert "Angkut dan lifting" in response.text
    assert "43,2 km" in response.text
    assert re.search(r"OPR-[0-9A-F]{32}", response.text)


def test_form_rejects_invalid_operation_and_preserves_useful_input(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "lifting",
                "lifting_hours": "",
                "total_distance_km": "18.5",
                "distance_source": "manual",
            },
        )

    assert response.status_code == 422
    assert "Periksa kembali data operasi" in response.text
    assert "Jam lifting harus lebih besar dari 0 untuk mode yang mencakup lifting." in response.text
    assert 'value="18.5"' in response.text
    assert '<option value="lifting" selected>' in response.text
    # The rejected submission is exactly the case where the planner still has
    # to enter lifting hours, so the field comes back visible rather than
    # hidden behind a mode change it has already made.
    assert '<div class="field" id="lifting-field">' in response.text


def test_form_asks_for_one_activity_and_lifting_total_for_the_whole_operation(
    tmp_path: Path,
) -> None:
    """Level 1 records the day as a whole: one activity, one lifting total.

    Per-stop activity belongs to a later level; asking for it here would put a
    field on the form that nothing in the trained model can read.
    """
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        form = client.get("/prediksi")
        response = client.post(
            "/operasi-harian",
            content=urlencode(
                [
                    ("vehicle_category", "ANGBER"),
                    ("vehicle", "Prime Mover"),
                    ("activity_mode", "transport_and_lifting"),
                    ("lifting_hours", "3.5"),
                    ("total_distance_km", "64"),
                    ("distance_source", "manual"),
                    ("stop_sequence", "Depo"),
                    ("stop_sequence", ""),
                    ("stop_sequence", "Site A"),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert form.status_code == 200
    assert 'name="activity_mode"' in form.text
    assert 'name="lifting_hours"' in form.text
    assert 'name="stop_activity"' not in form.text
    # The route itself is unchanged: stops are still ordered locations, and a
    # row left blank is simply not a stop.
    assert form.text.count('name="stop_sequence"') == 2
    assert response.status_code == 201
    assert "Angkut dan lifting" in response.text
    assert "Depo" in response.text
    assert "Site A" in response.text


def test_created_operation_remains_retrievable_after_app_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database_path)) as client:
        created = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "lifting_hours": None,
                "total_distance_km": 64.25,
                "distance_source": "routing_provider",
            },
        ).json()

    with TestClient(create_app(database_path=database_path)) as restarted_client:
        retrieved = restarted_client.get(f"/api/v1/daily-operations/{created['operation_id']}")

    assert retrieved.status_code == 200
    assert retrieved.json() == created


def test_api_rejects_distance_and_source_outside_contract(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 0,
                "distance_source": "perkiraan",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {"field": "total_distance_km", "message": "Jarak total harus lebih besar dari 0."},
            {"field": "distance_source", "message": "Sumber jarak tidak valid."},
        ]
    }


def test_api_rejects_lifting_hours_for_transport_only_operation(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "lifting_hours": 2,
                "total_distance_km": 30,
                "distance_source": "manual",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {
                "field": "lifting_hours",
                "message": "Jam lifting harus dikosongkan untuk mode transport.",
            }
        ]
    }


def test_api_returns_indonesian_feedback_for_unknown_operation(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.get("/api/v1/daily-operations/OPR-TIDAK-ADA")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "operation_not_found",
            "message": "Operasi harian tidak ditemukan.",
        }
    }
