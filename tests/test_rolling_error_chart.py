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
    # The threshold is a tick in the gutter, beside the dashed line; a label
    # on the line itself sat on the latest point.
    assert '<text class="trend-chart__text" x="42"' in after and ">5 L</text>" in after
    assert "Ambang 5 L" not in after
    # Every point can be hovered for its exact value; the table still lists them.
    assert after.count("<title>") >= 3
    assert "Tren kesalahan bergulir" in after


def test_a_threshold_tick_that_would_crowd_zero_is_left_out() -> None:
    from datetime import UTC, datetime

    from fuel_predictor.delivery.monitoring_pages import trend_chart
    from fuel_predictor.domain.monitoring import RollingErrorPoint

    moment = datetime(2026, 9, 1, tzinfo=UTC)
    point = RollingErrorPoint(observed_at=moment, mae_liters=100.0, matched_record_count=7)

    crowded = trend_chart([point], threshold_liters=5)
    clear = trend_chart([point], threshold_liters=50)

    assert crowded is not None and crowded["threshold_tick"] is None
    assert clear is not None and clear["threshold_tick"] == "50 L"


def test_an_end_label_moves_below_when_the_line_would_cross_it() -> None:
    from datetime import UTC, datetime, timedelta

    from fuel_predictor.delivery.monitoring_pages import trend_chart
    from fuel_predictor.domain.monitoring import RollingErrorPoint

    start = datetime(2026, 9, 1, tzinfo=UTC)

    def chart(*maes: float) -> list[dict[str, float]]:
        drawn = trend_chart(
            [
                RollingErrorPoint(
                    observed_at=start + timedelta(days=day), matched_record_count=7, mae_liters=mae
                )
                for day, mae in enumerate(maes)
            ],
            threshold_liters=5,
        )
        assert drawn is not None
        points = drawn["points"]
        assert isinstance(points, list)
        return points

    rising = chart(2.0, 9.0, 8.0)
    level = chart(8.0, 8.0, 8.0)

    # A steep rise runs through the space above the first point.
    assert rising[0]["value_y"] > rising[0]["y"]
    # Nothing crosses above a level line, so its labels stay above.
    assert level[0]["value_y"] < level[0]["y"]
    assert level[-1]["value_y"] < level[-1]["y"]
