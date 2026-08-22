"""Scheduled monitoring execution and its stored summaries (Phase 3).

Drift calculation and outcome reconciliation are expensive enough that doing
them inside a page request makes the dashboard slow exactly when it is being
watched. This runs them on a schedule and stores a compact summary the UI
(and later MCP) can read cheaply.

Monitoring failing must never interrupt prediction serving, so a failed run
is recorded as a failure and the process exits non-zero for the scheduler to
notice — it does not raise into anything that serves traffic.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


class RunOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MonitoringRun:
    run_id: str
    started_at: datetime
    finished_at: datetime
    outcome: RunOutcome
    trigger: str
    summary: dict[str, Any]
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is RunOutcome.SUCCEEDED


@dataclass(frozen=True, slots=True)
class BackupRun:
    run_id: str
    finished_at: datetime
    outcome: RunOutcome
    destination: str
    size_bytes: int | None = None
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is RunOutcome.SUCCEEDED


class MonitoringRunRepository(Protocol):
    def add(self, run: MonitoringRun) -> None: ...

    def latest(self) -> MonitoringRun | None: ...

    def latest_successful(self) -> MonitoringRun | None: ...

    def list_recent(self, limit: int) -> Sequence[MonitoringRun]: ...


class BackupRunRepository(Protocol):
    def add(self, run: BackupRun) -> None: ...

    def latest(self) -> BackupRun | None: ...

    def latest_successful(self) -> BackupRun | None: ...


@dataclass(frozen=True, slots=True)
class RunScheduledMonitoring:
    """Recompute the dashboard and store a summary of it.

    Idempotent by design: running it twice in a row produces two records of
    the same observation rather than double-counting anything, because the
    underlying dashboard is a pure read over current state. That means a
    scheduler that retries after a timeout cannot corrupt anything.
    """

    dashboard: Any
    runs: MonitoringRunRepository
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, trigger: str = "scheduled") -> MonitoringRun:
        started = self.now()
        run_id = f"MON-{uuid4().hex[:20]}"
        try:
            report = self.dashboard.execute()
        except Exception as error:  # noqa: BLE001 - recorded, never propagated to serving
            return self._record(
                MonitoringRun(
                    run_id=run_id,
                    started_at=started,
                    finished_at=self.now(),
                    outcome=RunOutcome.FAILED,
                    trigger=trigger,
                    summary={},
                    failure_reason=f"{type(error).__name__}: {error}",
                )
            )

        return self._record(
            MonitoringRun(
                run_id=run_id,
                started_at=started,
                finished_at=self.now(),
                outcome=RunOutcome.SUCCEEDED,
                trigger=trigger,
                summary=_summarise(report),
            )
        )

    def _record(self, run: MonitoringRun) -> MonitoringRun:
        """Store the outcome, tolerating a storage failure.

        When the database is unreachable, the dashboard fails *and* so does
        writing the failure down. Letting that second error escape would turn
        a recorded failure into an uncaught crash, which is precisely what
        this class exists to prevent — the caller still gets a run object
        describing what happened, and the non-zero exit code still reaches the
        scheduler.
        """
        try:
            self.runs.add(run)
        except Exception as error:  # noqa: BLE001 - nowhere left to record it
            if run.succeeded:
                return MonitoringRun(
                    run_id=run.run_id,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    outcome=RunOutcome.FAILED,
                    trigger=run.trigger,
                    summary=run.summary,
                    failure_reason=(
                        f"Pemantauan selesai tetapi hasilnya gagal disimpan: "
                        f"{type(error).__name__}: {error}"
                    ),
                )
        return run


def _summarise(report: Any) -> dict[str, Any]:
    """Compact, JSON-safe view of a dashboard, for cheap reads later.

    Deliberately stores counts and verdicts rather than whole row sets: this
    is a summary the UI shows at a glance, and keeping full detail here would
    grow without bound while duplicating what the source tables already hold.
    """
    drift = report.feature_drift
    return {
        "generated_at": report.generated_at.isoformat(),
        "active_alert_count": len(report.active_alerts),
        "critical_alert_count": sum(
            1 for alert in report.active_alerts if alert.severity.value == "critical"
        ),
        "unresolved_data_quality_issue_count": report.unresolved_data_quality_issue_count,
        "missing_actual_prediction_count": report.missing_actual_prediction_count,
        "drift_status": drift.status,
        "drift_share": drift.drift_share,
        "drift_threshold": drift.threshold,
        "drifting_features": list(drift.drifting_features),
        "degraded_categories": [
            item.vehicle_category.value for item in report.category_degradation if item.degraded
        ],
    }


@dataclass(frozen=True, slots=True)
class MonitoringFreshness:
    """How current the stored monitoring picture is."""

    last_success: datetime | None
    last_attempt: datetime | None
    last_attempt_failed: bool
    stale_after_hours: int
    now: datetime

    @property
    def is_stale(self) -> bool:
        """No successful run, or the last one is older than the allowance.

        A failed attempt does not by itself make the picture stale — the last
        good summary is still the best information available — but it is
        surfaced separately so an operator sees that monitoring is currently
        unhealthy even while the numbers still look fine.
        """
        if self.last_success is None:
            return True
        return self.now - self.last_success > timedelta(hours=self.stale_after_hours)

    @property
    def status_text(self) -> str:
        if self.last_success is None:
            return "Belum pernah berhasil dijalankan"
        if self.is_stale:
            return "Kedaluwarsa"
        if self.last_attempt_failed:
            return "Berhasil, tetapi percobaan terakhir gagal"
        return "Terkini"
