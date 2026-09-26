"""`python -m fuel_predictor monitor`, the scheduled check, runs and says so.

It builds the same monitoring checks the web app does (one builder,
`monitoring_wiring`), records the run for Kesehatan Sistem, and answers an
unreachable database with a sentence an operator can act on.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.__main__ import main
from fuel_predictor.infrastructure.database import build_engine, build_session_factory
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyMonitoringRunRepository,
)
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_a_scheduled_run_is_recorded_with_what_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "operations.sqlite3"
    with TestClient(create_app(database_path=database)) as client:
        _train_baseline(client)
        _operation_with_prediction(client, 24)
    url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", url)

    exit_code = main(["monitor", "--trigger", "manual"])

    assert exit_code == 0
    assert "Pemantauan selesai" in capsys.readouterr().out
    run = SqlAlchemyMonitoringRunRepository(build_session_factory(build_engine(url))).latest()
    assert run is not None and run.succeeded
    assert run.trigger == "manual"


def test_an_unreachable_database_is_named_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "FUEL_PREDICTOR_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'tidak-ada' / 'operations.sqlite3'}",
    )

    exit_code = main(["monitor"])

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "Pemantauan gagal" in error
    assert "Traceback" not in error
