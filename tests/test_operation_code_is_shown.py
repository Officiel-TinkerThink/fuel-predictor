"""The operation code is what the screens put in front of the operator.

The estimate is where the code gets written down, so it is shown large there
with a copy button; the `OPR-…` id moves to the technical details. Times are
shown in the site's time zone, so the time on the screen and the time in the
code agree.
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from fuel_predictor.delivery.rendering import format_datetime
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_the_estimate_leads_with_the_code_to_write_down(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]

        page = client.get(f"/operasi-harian/{operation['operation_id']}").text

    code = operation["operation_code"]
    assert "Kode operasi — catat kode ini" in page
    assert f'data-copy="{code}"' in page
    assert f'href="/bahan-bakar-aktual?operation_id={code}"' in page
    # Still there for an audit, behind the technical fold.
    technical = page.index('<details class="technical">')
    assert page.index(operation["operation_id"], technical) > technical


def test_the_saved_operation_shows_its_code(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        saved = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": "30",
                "distance_source": "manual",
            },
        )

    assert saved.status_code == 200, saved.text
    assert "Kode operasi — catat kode ini" in saved.text


def test_times_are_shown_in_the_site_time_zone() -> None:
    stored = datetime(2026, 9, 22, 23, 30, tzinfo=UTC)

    assert format_datetime(stored, ZoneInfo("Asia/Jakarta")) == "23/09/2026 06:30"
    # A value read back without its zone is a stored UTC time.
    assert format_datetime(stored.replace(tzinfo=None), ZoneInfo("Asia/Jakarta")) == (
        "23/09/2026 06:30"
    )
