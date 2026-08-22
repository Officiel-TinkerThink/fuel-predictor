from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from fuel_predictor.application.monitoring_runs import BackupRun, MonitoringRun, RunOutcome
from fuel_predictor.infrastructure.database import BackupRunRow, MonitoringRunRow, SessionFactory


class SqlAlchemyMonitoringRunRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, run: MonitoringRun) -> None:
        with self._session_factory.begin() as session:
            session.add(
                MonitoringRunRow(
                    run_id=run.run_id,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    outcome=str(run.outcome),
                    trigger=run.trigger,
                    failure_reason=run.failure_reason,
                    summary=run.summary,
                )
            )

    def latest(self) -> MonitoringRun | None:
        return self._first(self._ordered())

    def latest_successful(self) -> MonitoringRun | None:
        return self._first(
            self._ordered().where(MonitoringRunRow.outcome == str(RunOutcome.SUCCEEDED))
        )

    def list_recent(self, limit: int) -> tuple[MonitoringRun, ...]:
        with self._session_factory() as session:
            rows = session.execute(self._ordered().limit(limit)).scalars().all()
        return tuple(_run(row) for row in rows)

    def _ordered(self) -> Any:
        return select(MonitoringRunRow).order_by(
            MonitoringRunRow.finished_at.desc(), MonitoringRunRow.run_id.desc()
        )

    def _first(self, query: Any) -> MonitoringRun | None:
        with self._session_factory() as session:
            row = session.execute(query.limit(1)).scalar_one_or_none()
        return _run(row) if row is not None else None


class SqlAlchemyBackupRunRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, run: BackupRun) -> None:
        with self._session_factory.begin() as session:
            session.add(
                BackupRunRow(
                    run_id=run.run_id,
                    finished_at=run.finished_at,
                    outcome=str(run.outcome),
                    destination=run.destination,
                    size_bytes=run.size_bytes,
                    failure_reason=run.failure_reason,
                )
            )

    def latest(self) -> BackupRun | None:
        return self._first(self._ordered())

    def latest_successful(self) -> BackupRun | None:
        return self._first(self._ordered().where(BackupRunRow.outcome == str(RunOutcome.SUCCEEDED)))

    def _ordered(self) -> Any:
        return select(BackupRunRow).order_by(
            BackupRunRow.finished_at.desc(), BackupRunRow.run_id.desc()
        )

    def _first(self, query: Any) -> BackupRun | None:
        with self._session_factory() as session:
            row = session.execute(query.limit(1)).scalar_one_or_none()
        return _backup(row) if row is not None else None


def _run(row: MonitoringRunRow) -> MonitoringRun:
    return MonitoringRun(
        run_id=row.run_id,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        outcome=RunOutcome(row.outcome),
        trigger=row.trigger,
        summary=cast("dict[str, Any]", row.summary),
        failure_reason=row.failure_reason,
    )


def _backup(row: BackupRunRow) -> BackupRun:
    return BackupRun(
        run_id=row.run_id,
        finished_at=_aware(row.finished_at),
        outcome=RunOutcome(row.outcome),
        destination=row.destination,
        size_bytes=row.size_bytes,
        failure_reason=row.failure_reason,
    )


def _aware(moment: datetime) -> datetime:
    """SQLite loses the timezone PostgreSQL preserves; normalise to UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
