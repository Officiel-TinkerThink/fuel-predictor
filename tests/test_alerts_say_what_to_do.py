"""An alert on the page says what to do about it, in the words the guide promised.

The remediation text has lived in the domain since Phase 3 and reached the
webhook and e-mail notifiers - but the page showed only the alert kind as a
code ("missing_actual") and its one-line message. Three overdue operations
made three identical rows with no "Tindakan:" anywhere. The page now groups
alerts by kind, names the kind in words, and puts the remediation and its
urgency under the group once.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.domain.alert_remediation import remediation_for
from fuel_predictor.domain.monitoring import MonitoringAlertKind
from fuel_predictor.main import create_app
from tests.test_monitoring_dashboard import _prediction, _train_and_promote


def test_health_page_groups_alerts_and_shows_the_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FUEL_PREDICTOR_MISSING_ACTUAL_AFTER_DAYS", "1")
    database_path = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database_path)) as client:
        _train_and_promote(client)
        overdue = [_prediction(client)[0], _prediction(client)[0]]
        with create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}").begin() as db:
            for operation_id in overdue:
                db.execute(
                    text("UPDATE predictions SET created_at = :at WHERE operation_id = :id"),
                    {"at": datetime.now(UTC) - timedelta(days=2), "id": operation_id},
                )
        page = client.get("/pemantauan/kesehatan-sistem").text
        overview = client.get("/").text

    assert "Aktual belum dicatat" in page
    # Two alerts of one kind: one group, one remediation, both operations listed.
    assert page.count("Tindakan:") == 1
    assert remediation_for(MonitoringAlertKind.MISSING_ACTUAL)[:40] in page
    # Each named by its code and linked to the operation, where actual fuel is recorded.
    assert all(f'href="/operasi-harian/{operation_id}"' in page for operation_id in overdue)
    assert ">missing_actual<" not in page
    assert ">missing_actual<" not in overview
