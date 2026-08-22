from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.infrastructure.evidently_drift import EvidentlyFeatureDriftAnalyzer
from fuel_predictor.main import create_app


def _train_and_promote(client: TestClient) -> None:
    source = (
        "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        "ANGBER,transport,,20,18,manual\n"
        "ANGBER,transport,,40,28,manual\n"
        "ANGBER,lifting,2,20,25,manual\n"
    )
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", source.encode(), "text/csv")},
    ).json()["dataset_version"]
    candidate = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    ).json()
    promoted = client.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
    assert promoted.status_code == 200


def _prediction(client: TestClient, distance: float = 30) -> tuple[str, float]:
    operation = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport",
            "total_distance_km": distance,
            "distance_source": "manual",
        },
    ).json()
    prediction = client.post(
        f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
    ).json()
    return operation["operation_id"], prediction["estimated_fuel_requirement_liters"]


def test_monitoring_dashboard_reports_traceable_local_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FUEL_PREDICTOR_MISSING_ACTUAL_AFTER_DAYS", "1")
    database_path = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database_path)) as client:
        _train_and_promote(client)
        operation_id, estimate = _prediction(client)
        invalid = client.post(
            "/api/v1/historical-datasets",
            files={
                "file": (
                    "bermasalah.csv",
                    (
                        b"Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
                        b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
                        b"ANGBER,transport,,bukan-angka,20,manual\n"
                    ),
                    "text/csv",
                )
            },
        )
        assert invalid.status_code == 201
        database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        with create_engine(database_url).begin() as connection:
            connection.execute(
                text(
                    "UPDATE predictions SET created_at = :created_at "
                    "WHERE operation_id = :operation_id"
                ),
                {"created_at": datetime.now(UTC) - timedelta(days=2), "operation_id": operation_id},
            )
        dashboard = client.get("/api/v1/monitoring-dashboard")
        health_page = client.get("/pemantauan/kesehatan-sistem")
        recorded = client.post(
            f"/api/v1/daily-operations/{operation_id}/actual-fuel",
            json={"actual_fuel_liters": estimate, "measurement_source": "fuel_meter"},
        )
        recovered = client.get("/api/v1/monitoring-dashboard")

    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["unresolved_data_quality_issue_count"] == 1
    assert body["missing_actual_prediction_count"] == 1
    assert {alert["kind"] for alert in body["active_alerts"]} >= {
        "data_quality",
        "missing_actual",
    }
    assert all(alert["resolved_at"] is None for alert in body["active_alerts"])
    assert health_page.status_code == 200
    assert "Kesehatan Sistem" in health_page.text
    assert "Tidak ada promosi model otomatis" in health_page.text
    assert recorded.status_code == 201
    assert recovered.json()["missing_actual_prediction_count"] == 0
    assert "missing_actual" not in {alert["kind"] for alert in recovered.json()["active_alerts"]}
    with create_engine(database_url).connect() as connection:
        resolved_at = connection.execute(
            text("SELECT resolved_at FROM monitoring_alerts WHERE alert_key = :alert_key"),
            {"alert_key": f"missing_actual:{operation_id}"},
        ).scalar_one()
    assert resolved_at is not None


def test_monitoring_dashboard_shows_rolling_error_and_category_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FUEL_PREDICTOR_MAX_ACTIVE_MODEL_MAE_LITERS", "1")
    monkeypatch.setenv("FUEL_PREDICTOR_MONITORING_MIN_MATCHED_OUTCOMES", "1")
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_and_promote(client)
        operation_id, estimate = _prediction(client)
        actual = client.post(
            f"/api/v1/daily-operations/{operation_id}/actual-fuel",
            json={"actual_fuel_liters": estimate + 5, "measurement_source": "fuel_meter"},
        )
        dashboard = client.get("/api/v1/monitoring-dashboard")

    assert actual.status_code == 201
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["rolling_error_trend"][0]["mae_liters"] == 5.0
    assert body["category_degradation"][0]["degraded"] is True
    assert "model_degradation" in {alert["kind"] for alert in body["active_alerts"]}


def test_evidently_feature_drift_uses_its_dataset_and_column_metrics() -> None:
    reference = [
        {
            "vehicle_category": "ANGBER",
            "activity_mode": "transport" if value % 2 else "lifting",
            "distance_source": "manual",
            "total_distance_km": float(value),
            "lifting_hours": float(value % 3),
        }
        for value in range(20)
    ]
    current = [
        {
            "vehicle_category": "ANGBER",
            "activity_mode": "lifting" if value % 2 else "transport",
            "distance_source": "routing_provider",
            "total_distance_km": float(value + 100),
            "lifting_hours": float((value % 3) + 5),
        }
        for value in range(20)
    ]

    result = EvidentlyFeatureDriftAnalyzer().analyze(reference, current, 0.5)

    assert result.status == "ready"
    assert result.drift_share is not None
    assert result.drift_share >= result.threshold
    assert "total_distance_km" in result.drifting_features
