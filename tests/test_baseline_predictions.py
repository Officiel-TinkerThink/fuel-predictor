from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_HEADERS = (
    "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
)


def test_planner_can_train_a_traceable_baseline_and_predict_a_saved_operation(
    tmp_path: Path,
) -> None:
    historical_csv = _HEADERS + "\n".join(
        [
            "ANGBER,transport,,20,18,manual",
            "ANGBER,transport,,40,28,manual",
            "ANGBER,lifting,2,20,25,routing_provider",
            "ANGBER,transport_and_lifting,3,45,42,routing_provider",
        ]
    )
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        dataset = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat.csv", historical_csv.encode(), "text/csv")},
        ).json()["dataset_version"]
        candidate = client.post(
            f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
        )
        candidate_body = candidate.json()
        promoted = client.post(
            f"/api/v1/model-candidates/{candidate_body['model_version_id']}/promote"
        )
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport_and_lifting",
                "lifting_hours": 2,
                "total_distance_km": 35,
                "distance_source": "manual",
            },
        ).json()
        prediction = client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
        )
        form_prediction = client.post(f"/operasi-harian/{operation['operation_id']}/prediksi")

    assert candidate.status_code == 201
    assert candidate_body["model_version_id"].startswith("MDL-")
    assert candidate_body["dataset_version_id"] == dataset["dataset_version_id"]
    assert candidate_body["feature_version"] == "baseline-v1"
    assert candidate_body["algorithm"] == "linear_regression"
    assert candidate_body["lifecycle_status"] == "candidate"
    assert promoted.status_code == 200
    assert promoted.json()["lifecycle_status"] == "active"

    assert prediction.status_code == 201
    body = prediction.json()
    assert body["operation_id"] == operation["operation_id"]
    assert body["estimated_fuel_requirement_liters"] > 0
    assert body["recommended_allocation_liters"] >= body["estimated_fuel_requirement_liters"]
    assert body["uncertainty_interval_liters"]["lower"] <= body["estimated_fuel_requirement_liters"]
    assert body["uncertainty_interval_liters"]["upper"] >= body["estimated_fuel_requirement_liters"]
    assert body["route_distance_source"] == "manual"
    assert body["model"]["model_version_id"] == candidate_body["model_version_id"]
    assert body["lineage"] == {
        "input_operation_id": operation["operation_id"],
        "feature_version": "baseline-v1",
        "dataset_version_id": dataset["dataset_version_id"],
        "model_version_id": candidate_body["model_version_id"],
    }
    assert "bukan jaminan" in body["safety_policy"].lower()
    assert body["input_snapshot"]["total_distance_km"] == 35.0
    assert body["feature_values"]["lifting_hours"] == 2.0
    assert form_prediction.status_code == 201
    assert "Estimasi kebutuhan bahan bakar" in form_prediction.text
    assert "bukan konsumsi aktual" in form_prediction.text
