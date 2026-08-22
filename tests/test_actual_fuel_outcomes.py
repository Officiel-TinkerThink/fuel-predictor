from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, text

from fuel_predictor.main import create_app


def _train_baseline(client: TestClient) -> None:
    historical_csv = (
        "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        "ANGBER,transport,,20,18,manual\n"
        "ANGBER,transport,,40,28,manual\n"
        "ANGBER,lifting,2,20,25,manual\n"
    )
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", historical_csv.encode(), "text/csv")},
    ).json()["dataset_version"]
    response = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    )
    assert response.status_code == 201
    promoted = client.post(
        f"/api/v1/model-candidates/{response.json()['model_version_id']}/promote"
    )
    assert promoted.status_code == 200


def _operation_with_prediction(client: TestClient, distance: float) -> dict[str, dict[str, Any]]:
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
    return {"operation": operation, "prediction": prediction}


def test_actual_fuel_is_recorded_separately_and_performance_is_evaluated(tmp_path: Path) -> None:
    database_path = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database_path)) as client:
        _train_baseline(client)
        first = _operation_with_prediction(client, 24)
        second = _operation_with_prediction(client, 36)
        first_prediction = first["prediction"]
        second_prediction = second["prediction"]
        assert isinstance(first_prediction, dict)
        assert isinstance(second_prediction, dict)

        first_actual = client.post(
            f"/api/v1/daily-operations/{first['operation']['operation_id']}/actual-fuel",
            json={
                "actual_fuel_liters": first_prediction["estimated_fuel_requirement_liters"] + 2,
                "measurement_source": "fuel_meter",
            },
        )
        second_actual = client.post(
            f"/api/v1/daily-operations/{second['operation']['operation_id']}/actual-fuel",
            json={
                "actual_fuel_liters": second_prediction["estimated_fuel_requirement_liters"] - 2,
                "measurement_source": "manual_entry",
            },
        )
        performance = client.get("/api/v1/prediction-performance")

    assert first_actual.status_code == 201
    assert first_actual.json()["measurement_source"] == "fuel_meter"
    assert first_actual.json()["status"] == "recorded"
    assert second_actual.status_code == 201
    assert performance.status_code == 200
    overall = performance.json()["overall"]
    assert overall["matched_record_count"] == 2
    assert overall["mae_liters"] == 2.0
    assert overall["rmse_liters"] == 2.0
    assert overall["smape_percent"] is not None
    assert overall["interval_coverage_percent"] is not None
    assert performance.json()["by_vehicle_category"][0]["vehicle_category"] == "ANGBER"

    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    with create_engine(database_url).connect() as connection:
        table_info = connection.execute(text("PRAGMA table_info(historical_daily_operations)"))
        prepared_fuel_columns = {row[1] for row in table_info}
        actual = connection.execute(
            text("SELECT actual_fuel_liters, measurement_source, status FROM actual_fuel_records")
        ).all()
    assert "prepared_fuel_liters" in prepared_fuel_columns
    assert {row[1] for row in actual} == {"fuel_meter", "manual_entry"}


def test_bulk_actual_fuel_keeps_valid_rows_and_reports_unmatched_or_invalid_rows(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        item = _operation_with_prediction(client, 30)
        operation = item["operation"]
        prediction = item["prediction"]
        assert isinstance(operation, dict)
        assert isinstance(prediction, dict)
        bulk_csv = (
            "ID Operasi (wajib),Bahan Bakar Aktual (L) (wajib),Sumber Pengukuran (opsional)\n"
            f"{operation['operation_id']},{prediction['estimated_fuel_requirement_liters']},fuel_meter\n"
            "OPR-TIDAK-ADA,25,manual_entry\n"
            f"{operation['operation_id']},bukan-angka,manual_entry\n"
        )
        response = client.post(
            "/api/v1/bulk-actual-fuel",
            files={"file": ("aktual.csv", bulk_csv.encode(), "text/csv")},
        )
        template = client.get("/api/v1/bulk-actual-fuel/template?format=xlsx")

    assert response.status_code == 201
    body = response.json()
    assert body["accepted_row_count"] == 1
    assert body["quarantined_row_count"] == 2
    assert body["accepted_rows"][0]["actual_fuel"]["measurement_source"] == "fuel_meter"
    assert body["correction_report"][0]["reasons"][0]["field"] == "operation_id"
    assert body["correction_report"][1]["reasons"][0]["field"] == "actual_fuel_liters"
    assert template.status_code == 200
    workbook = load_workbook(BytesIO(template.content), data_only=True)
    assert workbook["Bahan Bakar Aktual"]["A1"].value == "ID Operasi (wajib)"


def test_actual_fuel_form_and_api_reject_duplicate_records(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        item = _operation_with_prediction(client, 30)
        operation = item["operation"]
        assert isinstance(operation, dict)
        form = client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": operation["operation_id"],
                "actual_fuel_liters": "26.5",
                "measurement_source": "manual_entry",
            },
        )
        duplicate = client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/actual-fuel",
            json={"actual_fuel_liters": 26.5, "measurement_source": "manual_entry"},
        )

    assert form.status_code == 201
    assert "Bahan bakar aktual tersimpan" in form.text
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "actual_fuel_already_recorded"
