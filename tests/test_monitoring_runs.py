"""Scheduled monitoring runs and freshness (Phase 3)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fuel_predictor.application.monitoring_runs import (
    BackupRun,
    MonitoringFreshness,
    RunOutcome,
    RunScheduledMonitoring,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyBackupRunRepository,
    SqlAlchemyMonitoringRunRepository,
)

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _Alert:
    def __init__(self, severity: str) -> None:
        self.severity = type("S", (), {"value": severity})()


class _Drift:
    status = "ready"
    drift_share = 0.25
    threshold = 0.5
    drifting_features = ("total_distance_km",)


class _Degradation:
    def __init__(self, category: str, degraded: bool) -> None:
        self.vehicle_category = type("C", (), {"value": category})()
        self.degraded = degraded


class _Report:
    generated_at = _NOW
    active_alerts = (_Alert("warning"), _Alert("critical"))
    unresolved_data_quality_issue_count = 3
    missing_actual_prediction_count = 2
    feature_drift = _Drift()
    category_degradation = (_Degradation("ANGBER", True), _Degradation("OTHER", False))


class _Dashboard:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def execute(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _Report()


@pytest.fixture
def runs(tmp_path: Path) -> SqlAlchemyMonitoringRunRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'runs.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyMonitoringRunRepository(build_session_factory(engine))


@pytest.fixture
def backups(tmp_path: Path) -> SqlAlchemyBackupRunRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'backups.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyBackupRunRepository(build_session_factory(engine))


def test_a_successful_run_stores_a_compact_summary(
    runs: SqlAlchemyMonitoringRunRepository,
) -> None:
    run = RunScheduledMonitoring(dashboard=_Dashboard(), runs=runs, now=lambda: _NOW).execute()

    assert run.succeeded is True
    stored = runs.latest()
    assert stored is not None
    assert stored.summary["active_alert_count"] == 2
    assert stored.summary["critical_alert_count"] == 1
    assert stored.summary["missing_actual_prediction_count"] == 2
    assert stored.summary["drift_status"] == "ready"
    assert stored.summary["degraded_categories"] == ["ANGBER"]


def test_a_failing_dashboard_is_recorded_rather_than_raised(
    runs: SqlAlchemyMonitoringRunRepository,
) -> None:
    """Monitoring failing must never take down anything that serves traffic."""
    run = RunScheduledMonitoring(
        dashboard=_Dashboard(error=RuntimeError("drift engine unavailable")),
        runs=runs,
        now=lambda: _NOW,
    ).execute()

    assert run.succeeded is False
    assert run.failure_reason is not None
    assert "drift engine unavailable" in run.failure_reason
    stored = runs.latest()
    assert stored is not None and stored.outcome is RunOutcome.FAILED


def test_running_twice_records_two_observations_without_double_counting(
    runs: SqlAlchemyMonitoringRunRepository,
) -> None:
    """Idempotent: a scheduler retrying after a timeout cannot corrupt anything."""
    runner = RunScheduledMonitoring(dashboard=_Dashboard(), runs=runs, now=lambda: _NOW)

    first = runner.execute()
    second = runner.execute()

    assert first.run_id != second.run_id
    assert len(runs.list_recent(10)) == 2
    assert first.summary == second.summary


def test_the_last_successful_run_survives_a_later_failure(
    runs: SqlAlchemyMonitoringRunRepository,
) -> None:
    """A failed attempt must not erase the last good picture."""
    RunScheduledMonitoring(dashboard=_Dashboard(), runs=runs, now=lambda: _NOW).execute()
    RunScheduledMonitoring(
        dashboard=_Dashboard(error=RuntimeError("boom")),
        runs=runs,
        now=lambda: _NOW + timedelta(hours=1),
    ).execute()

    assert runs.latest() is not None and runs.latest().outcome is RunOutcome.FAILED  # type: ignore[union-attr]
    successful = runs.latest_successful()
    assert successful is not None
    assert successful.summary["active_alert_count"] == 2


def test_freshness_reports_never_run() -> None:
    freshness = MonitoringFreshness(
        last_success=None,
        last_attempt=None,
        last_attempt_failed=False,
        stale_after_hours=26,
        now=_NOW,
    )

    assert freshness.is_stale is True
    assert "Belum pernah" in freshness.status_text


def test_freshness_reports_stale_after_the_allowance() -> None:
    freshness = MonitoringFreshness(
        last_success=_NOW - timedelta(hours=48),
        last_attempt=_NOW - timedelta(hours=48),
        last_attempt_failed=False,
        stale_after_hours=26,
        now=_NOW,
    )

    assert freshness.is_stale is True
    assert freshness.status_text == "Kedaluwarsa"


def test_a_recent_failure_is_surfaced_even_while_the_numbers_are_still_current() -> None:
    """The picture is usable but monitoring is unhealthy; say both."""
    freshness = MonitoringFreshness(
        last_success=_NOW - timedelta(hours=2),
        last_attempt=_NOW - timedelta(minutes=5),
        last_attempt_failed=True,
        stale_after_hours=26,
        now=_NOW,
    )

    assert freshness.is_stale is False
    assert "percobaan terakhir gagal" in freshness.status_text


def test_a_healthy_recent_run_reads_as_current() -> None:
    freshness = MonitoringFreshness(
        last_success=_NOW - timedelta(hours=1),
        last_attempt=_NOW - timedelta(hours=1),
        last_attempt_failed=False,
        stale_after_hours=26,
        now=_NOW,
    )

    assert freshness.is_stale is False
    assert freshness.status_text == "Terkini"


def test_backup_outcomes_round_trip(backups: SqlAlchemyBackupRunRepository) -> None:
    backups.add(
        BackupRun(
            run_id="BAK-1",
            finished_at=_NOW,
            outcome=RunOutcome.SUCCEEDED,
            destination="s3://cadangan/harian",
            size_bytes=1024,
        )
    )

    latest = backups.latest()
    assert latest is not None
    assert latest.succeeded is True
    assert latest.destination == "s3://cadangan/harian"


def test_a_failed_backup_does_not_hide_the_last_successful_one(
    backups: SqlAlchemyBackupRunRepository,
) -> None:
    backups.add(
        BackupRun(
            run_id="BAK-1",
            finished_at=_NOW - timedelta(days=1),
            outcome=RunOutcome.SUCCEEDED,
            destination="s3://cadangan/harian",
        )
    )
    backups.add(
        BackupRun(
            run_id="BAK-2",
            finished_at=_NOW,
            outcome=RunOutcome.FAILED,
            destination="s3://cadangan/harian",
            failure_reason="kredensial ditolak",
        )
    )

    assert backups.latest() is not None and backups.latest().succeeded is False  # type: ignore[union-attr]
    last_good = backups.latest_successful()
    assert last_good is not None
    assert last_good.run_id == "BAK-1"


class _BrokenRepository:
    """A store that cannot accept writes — the database-is-down case."""

    def add(self, run: Any) -> None:
        raise RuntimeError("database unreachable")

    def latest(self) -> Any:
        raise RuntimeError("database unreachable")

    def latest_successful(self) -> Any:
        raise RuntimeError("database unreachable")

    def list_recent(self, limit: int) -> Any:
        raise RuntimeError("database unreachable")


def test_a_failure_that_cannot_even_be_recorded_does_not_crash() -> None:
    """When the database is down, both the run and recording it fail.

    Letting the second failure escape would turn a recorded failure into an
    uncaught crash — exactly what this class exists to prevent. The caller
    must still get a run object so the CLI can exit non-zero for the
    scheduler.
    """
    run = RunScheduledMonitoring(
        dashboard=_Dashboard(error=RuntimeError("database unreachable")),
        runs=_BrokenRepository(),
        now=lambda: _NOW,
    ).execute()

    assert run.succeeded is False
    assert run.failure_reason is not None


def test_a_successful_run_whose_result_cannot_be_stored_is_reported_as_failed() -> None:
    """Monitoring that ran but could not be persisted has not really succeeded.

    Reporting success would leave the dashboard showing a stale picture while
    the scheduler saw a green run and raised no alarm.
    """
    run = RunScheduledMonitoring(
        dashboard=_Dashboard(), runs=_BrokenRepository(), now=lambda: _NOW
    ).execute()

    assert run.succeeded is False
    assert run.failure_reason is not None
    assert "gagal disimpan" in run.failure_reason
