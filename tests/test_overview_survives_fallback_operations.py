"""Recording actual fuel for a route that fell back to a manual distance must
not take the overview down.

The evaluation reader rebuilt each DailyOperation from its row alone, without
its stops. A fallback operation (routing unavailable, planner typed the
distance) then failed the domain invariant "a manual fallback needs a stop
sequence", and every page that evaluates the active model - the overview, the
model governance page - answered with a JSON validation error instead of HTML.
It surfaced the first time someone did the right thing: reported the real
consumption for a day the route service had been down.
"""

import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline


def test_overview_and_model_page_still_render(tmp_path: Path) -> None:
    # No routing provider configured: the typed distance is the fallback.
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        saved = client.post(
            "/operasi-harian",
            content=urlencode(
                [
                    ("vehicle_category", "ANGBER"),
                    ("activity_mode", "transport"),
                    ("total_distance_km", "50"),
                    ("distance_source", "manual"),
                    ("stop_sequence", "Depo"),
                    ("stop_sequence", "Site A"),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        operation_id = re.findall(r"OPR-[0-9A-F]{32}", saved.text)[0]
        recorded = client.post(
            f"/api/v1/daily-operations/{operation_id}/actual-fuel",
            json={"actual_fuel_liters": 30, "measurement_source": "fuel_meter"},
        )
        overview = client.get("/")
        governance = client.get("/pengelolaan-model")

    assert saved.status_code == 201, saved.text
    assert recorded.status_code == 201, recorded.text
    assert overview.status_code == 200, overview.text
    assert "Ringkasan" in overview.text
    assert governance.status_code == 200, governance.text
