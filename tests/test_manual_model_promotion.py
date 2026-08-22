from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_HEADERS = (
    "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
)


def _train_candidate(client: TestClient, filename: str, rows: list[str]) -> dict[str, Any]:
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": (filename, (_HEADERS + "\n".join(rows)).encode(), "text/csv")},
    ).json()["dataset_version"]
    response = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _operation_with_actual(client: TestClient, distance: float) -> None:
    operation = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport",
            "total_distance_km": distance,
            "distance_source": "manual",
        },
    ).json()
    prediction_response = client.post(
        f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
    )
    assert prediction_response.status_code == 201, prediction_response.text
    prediction = prediction_response.json()
    actual = client.post(
        f"/api/v1/daily-operations/{operation['operation_id']}/actual-fuel",
        json={
            "actual_fuel_liters": prediction["estimated_fuel_requirement_liters"] + 2,
            "measurement_source": "fuel_meter",
        },
    )
    assert actual.status_code == 201


def test_candidate_requires_manual_promotion_and_preserves_model_history(tmp_path: Path) -> None:
    rows = [
        "ANGBER,transport,,20,18,manual",
        "ANGBER,transport,,40,28,manual",
        "ANGBER,lifting,2,20,25,manual",
    ]
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        first = _train_candidate(client, "first.csv", rows)
        pending_operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 18,
                "distance_source": "manual",
            },
        ).json()
        no_active_prediction = client.post(
            f"/api/v1/daily-operations/{pending_operation['operation_id']}/predictions"
        )
        first_promoted = client.post(
            f"/api/v1/model-candidates/{first['model_version_id']}/promote"
        )
        assert first_promoted.status_code == 200, first_promoted.text
        _operation_with_actual(client, 24)
        second = _train_candidate(
            client,
            "second.csv",
            [
                "ANGBER,transport,,20,20,manual",
                "ANGBER,transport,,40,31,manual",
                "ANGBER,lifting,2,20,27,manual",
            ],
        )
        comparison = client.get(f"/api/v1/model-candidates/{second['model_version_id']}/comparison")
        dashboard = client.get("/api/v1/model-governance-dashboard")
        second_promoted = client.post(
            f"/api/v1/model-candidates/{second['model_version_id']}/promote"
        )
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 30,
                "distance_source": "manual",
            },
        ).json()
        new_prediction = client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
        )
        old_as_candidate = client.get(
            f"/api/v1/model-candidates/{first['model_version_id']}/comparison"
        )

    assert first["lifecycle_status"] == "candidate"
    assert no_active_prediction.status_code == 409
    assert first_promoted.status_code == 200
    assert first_promoted.json()["lifecycle_status"] == "active"
    assert comparison.status_code == 200
    assert comparison.json()["candidate_overall"]["matched_record_count"] == 1
    assert comparison.json()["active_overall"]["matched_record_count"] == 1
    assert comparison.json()["by_vehicle_category"][0]["vehicle_category"] == "ANGBER"
    assert dashboard.status_code == 200
    assert dashboard.json()["active_model"]["model_version_id"] == first["model_version_id"]
    assert dashboard.json()["candidate_models"][0]["model_version_id"] == second["model_version_id"]
    assert "manual" in dashboard.json()["recommendation"].lower()
    assert second_promoted.status_code == 200
    assert new_prediction.status_code == 201
    assert new_prediction.json()["model"]["model_version_id"] == second["model_version_id"]
    assert new_prediction.json()["model"]["lifecycle_status"] == "active"
    assert old_as_candidate.status_code == 404
