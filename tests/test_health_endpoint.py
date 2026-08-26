"""`/sehat` is what an external watchdog polls.

The runbook says a dead-man's-switch has to live outside the deployment,
because nothing inside can notice that the deployment stopped. Until now it
asked for that watchdog without giving it anything to poll — `/sehat` was
listed as a public path and never implemented.

It is unauthenticated on purpose, so it must not become a place to read the
system's internals from the open internet.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy
from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "operations.sqlite3"


def _client(database: Path) -> TestClient:
    return TestClient(create_app(database_path=database, allow_unprovisioned_access=False))


def test_it_answers_without_a_session(database: Path) -> None:
    """A watchdog that needs to sign in stops working exactly when sessions break."""
    with _client(database) as client:
        response = client.get("/sehat")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_it_answers_even_when_the_application_is_locked_down(database: Path) -> None:
    """Fail-closed auth must not also lock out the health check."""
    with _client(database) as client:
        assert client.get("/", follow_redirects=False).status_code in (303, 401)

        assert client.get("/sehat").status_code == 200


def test_it_reports_the_database_as_reachable(database: Path) -> None:
    with _client(database) as client:
        body = client.get("/sehat").json()

    assert body["database"] == "ok"


def test_monitoring_is_unknown_before_the_first_run(database: Path) -> None:
    """Never having run is not the same as having stopped.

    Reporting a brand-new deployment as stale would page somebody on day one.
    """
    with _client(database) as client:
        body = client.get("/sehat").json()

    assert body["monitoring_stale"] is None


def test_a_recent_monitoring_run_is_not_stale(database: Path) -> None:
    with _client(database) as client:
        _record_run(database, finished_at=datetime.now(UTC))
        body = client.get("/sehat").json()

    assert body["monitoring_stale"] is False


def test_monitoring_that_stopped_running_is_reported_as_stale(database: Path) -> None:
    """The whole point: a watchdog reading this can tell the job died."""
    with _client(database) as client:
        _record_run(database, finished_at=datetime.now(UTC) - timedelta(days=30))
        body = client.get("/sehat").json()

    assert body["monitoring_stale"] is True
    # Still 200: the application is answering. Taking it out of a load balancer
    # because a scheduled job is late would be the wrong response.
    assert client.get("/sehat").status_code == 200


def test_it_leaks_nothing_about_the_system(database: Path) -> None:
    """Unauthenticated, so the body is a deliberate allow-list, not a dump."""
    with _client(database) as client:
        body = client.get("/sehat").json()

    assert set(body) == {"status", "database", "monitoring_stale"}
    text = client.get("/sehat").text.lower()
    for leak in ("sqlite", "postgres", "password", "token", "traceback", "/", "version"):
        assert leak not in text, f"health response mentions {leak!r}"


def _record_run(database: Path, finished_at: datetime) -> None:
    engine = sqlalchemy.create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO monitoring_runs"
                " (run_id, started_at, finished_at, outcome, trigger, summary)"
                " VALUES ('MON-test', :finished_at, :finished_at, 'succeeded', 'test', '{}')"
            ),
            {"finished_at": finished_at},
        )
