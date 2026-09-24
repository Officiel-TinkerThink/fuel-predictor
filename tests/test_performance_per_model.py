"""Field performance is read per model, not pooled across every model ever active.

The page used to report one MAE under "Seberapa tepat model aktif" while
averaging every prediction of every model. After a promotion, the new model's
figures were mixed with its predecessor's. Each matched actual is now
attributed to the model whose prediction it is compared with.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.application.actual_fuel import (
    PredictionOutcome,
    calculate_performance_metrics,
)
from fuel_predictor.domain.daily_operation import VehicleCategory
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_bias_says_which_way_the_estimates_miss() -> None:
    outcomes = [
        PredictionOutcome(VehicleCategory.ANGBER, 10.0, 8.0, 12.0, 14.0),
        PredictionOutcome(VehicleCategory.ANGBER, 20.0, 18.0, 22.0, 22.0),
    ]

    metrics = calculate_performance_metrics(outcomes)

    # Both under: -4 and -2.
    assert metrics.bias_liters == pytest.approx(-3.0)


def _record_actual(client: TestClient, operation_id: str, litres: float) -> None:
    response = client.post(
        f"/api/v1/daily-operations/{operation_id}/actual-fuel",
        json={"actual_fuel_liters": litres, "measurement_source": "fuel_meter"},
    )
    assert response.status_code == 201, response.text


def _predict_and_record(client: TestClient, distance: float, litres: float) -> dict[str, Any]:
    item = _operation_with_prediction(client, distance)
    _record_actual(client, item["operation"]["operation_id"], litres)
    return item["prediction"]


def test_each_model_is_measured_on_its_own_predictions(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        first = _predict_and_record(client, 24, 20.0)
        _predict_and_record(client, 36, 30.0)
        _train_baseline(client)
        second = _predict_and_record(client, 30, 25.0)

        report = client.get("/api/v1/prediction-performance").json()
        page = client.get("/pemantauan/kinerja-model").text

    by_code = {row["model_code"]: row for row in report["by_model"]}
    first_code = first["model"]["model_code"]
    second_code = second["model"]["model_code"]
    assert first_code != second_code
    assert by_code[first_code]["matched_record_count"] == 2
    assert by_code[second_code]["matched_record_count"] == 1
    assert by_code[second_code]["lifecycle_status"] == "active"
    assert by_code[first_code]["declared_mae_liters"] == first["model"]["uncertainty_liters"]
    assert report["overall"]["matched_record_count"] == 3
    assert first_code in page and second_code in page


def test_a_freshly_promoted_model_is_listed_before_any_actual(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        prediction = _operation_with_prediction(client, 24)["prediction"]

        report = client.get("/api/v1/prediction-performance").json()

    rows = report["by_model"]
    assert [row["model_code"] for row in rows] == [prediction["model"]["model_code"]]
    assert rows[0]["matched_record_count"] == 0
    assert rows[0]["mae_liters"] is None
