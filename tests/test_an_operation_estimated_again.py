"""An operation estimated again is one operation, read at its last estimate.

Every list that pairs an operation with its estimate - the history, the
operations waiting for actual fuel, the error measured once actual fuel is
in - picks the newest prediction through one shared subquery. The rule is
held here: estimated twice, an operation appears once, with the second
estimate, everywhere.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import format_decimal
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _train_a_hungrier_baseline(client: TestClient) -> None:
    """History where the same distances took more fuel, so its model's
    estimate for the operation differs from the first model's."""
    history = (
        "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        "ANGBER,transport,,20,40,manual\n"
        "ANGBER,transport,,40,70,manual\n"
        "ANGBER,lifting,2,20,55,manual\n"
    )
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat-2.csv", history.encode(), "text/csv")},
    ).json()["dataset_version"]
    candidate = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    ).json()
    promoted = client.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
    assert promoted.status_code == 200, promoted.text


def test_an_operation_estimated_twice_is_read_at_its_second_estimate(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        planned = _operation_with_prediction(client, 30)
        operation: dict[str, Any] = planned["operation"]
        first: dict[str, Any] = planned["prediction"]
        _train_a_hungrier_baseline(client)
        second = client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
        ).json()
        code = operation["operation_code"]

        history = client.get("/riwayat-prediksi?per=50").text
        waiting = client.get("/bahan-bakar-aktual").text
        client.post(
            f"/api/v1/daily-operations/{code}/actual-fuel",
            json={"actual_fuel_liters": 50, "measurement_source": "fuel_meter"},
        )
        performance = client.get("/api/v1/prediction-performance").json()["overall"]

    assert second["recommended_allocation_liters"] != first["recommended_allocation_liters"]
    latest = format_decimal(second["recommended_allocation_liters"])
    earlier = format_decimal(first["recommended_allocation_liters"])
    assert history.count(f">{code}<") == 1
    assert f"{latest} L" in history and f"{earlier} L" not in history
    assert waiting.count(f">{code}<") == 1
    assert f"{latest} L" in waiting and f"{earlier} L" not in waiting
    # The error is measured once, against the estimate the operation went out with.
    assert performance["matched_record_count"] == 1
    assert performance["mae_liters"] == abs(50 - second["estimated_fuel_requirement_liters"])
