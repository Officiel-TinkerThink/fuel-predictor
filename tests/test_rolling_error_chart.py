"""Kinerja Model draws the rolling error, not only lists it.

"Is it getting worse?" is a shape question; a column of numbers answers it
only after arithmetic. The page now draws the rolling MAE as a line with
the degradation threshold across it, first and last values labelled, and a
title on every point for hover. The table underneath stays as the exact
and accessible reading of the same points.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def _record(client: TestClient, distance: float, offset: float) -> None:
    item = _operation_with_prediction(client, distance)
    client.post(
        f"/api/v1/daily-operations/{item['operation']['operation_id']}/actual-fuel",
        json={
            "actual_fuel_liters": item["prediction"]["estimated_fuel_requirement_liters"] + offset,
            "measurement_source": "fuel_meter",
        },
    )


def test_the_trend_is_drawn_once_there_are_points(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        before = client.get("/pemantauan/kinerja-model").text
        for distance, offset in ((24, 1.0), (36, 2.0), (30, 4.0)):
            _record(client, distance, offset)
        after = client.get("/pemantauan/kinerja-model").text

    assert 'class="trend-chart"' not in before
    assert 'class="trend-chart"' in after
    assert 'role="img"' in after
    assert "Ambang 5 L" in after
    # Every point can be hovered for its exact value; the table still lists them.
    assert after.count("<title>") >= 3
    assert "Tren kesalahan bergulir" in after
