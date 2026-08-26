"""Liveness endpoint for an external watchdog (`/sehat`).

Nothing inside a deployment can detect that the deployment stopped running, and
nothing inside it can detect that its own scheduled monitoring died. A
dead-man's-switch has to live outside the thing it watches, and until now the
runbook asked for one without giving it anything to poll.

Deliberately unauthenticated — a watchdog that needs a session is a watchdog
that stops working when sessions break — so it says as little as it can while
still being useful: whether the database answers, and whether scheduled
monitoring has run recently. No counts, no identifiers, no timestamps. The
detailed picture stays behind the sign-in on Kesehatan Sistem.

The status code means one thing only: can this instance serve requests. A stale
monitor does not make it 503, because the application is still answering and
taking it out of a load balancer would be the wrong response. Staleness is
reported in the body for a watchdog that reads it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from fuel_predictor.application.monitoring_runs import MonitoringRunRepository
from fuel_predictor.infrastructure.database import SessionFactory


def build_health_router(
    session_factory: SessionFactory,
    monitoring_runs: MonitoringRunRepository,
    monitoring_stale_after_hours: int,
) -> APIRouter:
    router = APIRouter()

    @router.get("/sehat")
    def health() -> JSONResponse:
        body: dict[str, Any] = {"status": "ok", "database": "ok", "monitoring_stale": None}

        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - the reason belongs in the logs, not here
            # No detail in the response: this is unauthenticated, and a
            # connection string in an error message is exactly the kind of
            # thing that should not be readable from the open internet.
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "unavailable", "database": "unreachable"},
            )

        try:
            successful = monitoring_runs.latest_successful()
        except Exception:  # noqa: BLE001 - liveness must not depend on this
            return JSONResponse(content=body)

        if successful is None:
            # Never having run is not the same as having stopped, and on a new
            # deployment it is expected. Reported as unknown rather than stale
            # so a watchdog does not page anybody on day one.
            body["monitoring_stale"] = None
        else:
            allowance = timedelta(hours=monitoring_stale_after_hours)
            body["monitoring_stale"] = datetime.now(UTC) - successful.finished_at > allowance

        return JSONResponse(content=body)

    return router
