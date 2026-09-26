"""Kesehatan Sistem says whether the database was backed up, and where to.

Production had never been backed up: the encrypted off-site job needs a key
and a remote nobody had configured, and nothing else ran. A `backup` service
now dumps the database daily (deploy/local-backup.sh) and records each run;
the page shows the last one with its destination, and until there is one,
says which service does it.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.application.monitoring_runs import BackupRun, RunOutcome
from fuel_predictor.infrastructure.database import build_engine, build_session_factory
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyBackupRunRepository,
)
from fuel_predictor.main import create_app

_COMPOSE = Path(__file__).resolve().parents[1] / "compose.prod.yaml"
_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "local-backup.sh"


def test_before_any_backup_the_page_names_the_service_that_makes_them(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/pemantauan/kesehatan-sistem").text

    assert "Belum pernah dibuat" in page
    assert "<code>backup</code>" in page


def test_the_last_backup_is_shown_with_where_it_went(tmp_path: Path) -> None:
    database = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database)) as client:
        SqlAlchemyBackupRunRepository(
            build_session_factory(build_engine(f"sqlite+pysqlite:///{database}"))
        ).add(
            BackupRun(
                run_id="BAK-1",
                finished_at=datetime(2026, 9, 26, 3, 0, tzinfo=UTC),
                outcome=RunOutcome.SUCCEEDED,
                destination="lokal: volume db_backups (7 hari)",
                size_bytes=2332,
                failure_reason=None,
            )
        )
        page = client.get("/pemantauan/kesehatan-sistem").text

    assert "Berhasil" in page
    assert "Ke lokal: volume db_backups (7 hari)." in page


def test_the_backup_service_ships_with_the_deployment() -> None:
    compose = _COMPOSE.read_text()
    script = _SCRIPT.read_text()

    assert "\n  backup:\n" in compose
    assert "./deploy/local-backup.sh:/deploy/local-backup.sh:ro" in compose
    assert "db_backups:/backups" in compose
    # Seven days kept, each run recorded where Kesehatan Sistem reads it.
    assert 'KEEP_DAYS="${LOCAL_BACKUP_KEEP_DAYS:-7}"' in script
    assert "INSERT INTO backup_runs" in script
