"""Command-line entry points for scheduled work (Phase 3).

    python -m fuel_predictor monitor

Run by the host scheduler or a small Compose job. Exits non-zero when a run
fails so the scheduler notices, which is the signal the plan's failed-run
alerting depends on — a job that always exits zero cannot be monitored.
"""

import argparse
import sys
from collections.abc import Sequence

from fuel_predictor.application.monitoring_runs import RunScheduledMonitoring
from fuel_predictor.configuration import ApplicationSettings
from fuel_predictor.infrastructure.database import build_engine, build_session_factory
from fuel_predictor.infrastructure.evidently_drift import EvidentlyFeatureDriftAnalyzer
from fuel_predictor.infrastructure.sqlalchemy_monitoring import SqlAlchemyMonitoringRepository
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyMonitoringRunRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fuel_predictor")
    subcommands = parser.add_subparsers(dest="command", required=True)
    monitor = subcommands.add_parser(
        "monitor", help="Hitung ulang pemantauan dan simpan ringkasannya."
    )
    monitor.add_argument(
        "--trigger",
        default="scheduled",
        help="Label sumber pemicu, misalnya 'scheduled' atau 'manual'.",
    )

    arguments = parser.parse_args(argv)
    if arguments.command == "monitor":
        return _run_monitoring(arguments.trigger)
    return 2


def _run_monitoring(trigger: str) -> int:
    from fuel_predictor.application.monitoring import GetMonitoringDashboard

    settings = ApplicationSettings()
    try:
        session_factory = build_session_factory(build_engine(settings.database_url))
        monitoring_repository = SqlAlchemyMonitoringRepository(session_factory)
        prediction_repository = SqlAlchemyPredictionRepository(session_factory)
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        # A database that cannot be reached cannot record its own failure, so
        # this is the one case where the only report is what is printed here.
        # A raw traceback would tell a non-technical operator nothing about
        # what to do next.
        print(
            "Pemantauan gagal: basis data tidak dapat dihubungi. Periksa layanan "
            f"PostgreSQL dan FUEL_PREDICTOR_DATABASE_URL. Detail: {error}",
            file=sys.stderr,
        )
        return 1

    run = RunScheduledMonitoring(
        dashboard=GetMonitoringDashboard(
            monitoring_repository,
            prediction_repository,
            monitoring_repository,
            EvidentlyFeatureDriftAnalyzer(),
            settings.missing_actual_after_days,
            settings.monitoring_drift_share_threshold,
            settings.monitoring_rolling_error_window,
            settings.max_active_model_mae_liters,
            settings.monitoring_min_matched_outcomes,
        ),
        runs=SqlAlchemyMonitoringRunRepository(session_factory),
    ).execute(trigger=trigger)

    if run.succeeded:
        summary = run.summary
        print(
            f"Pemantauan selesai: {summary['active_alert_count']} peringatan aktif, "
            f"{summary['missing_actual_prediction_count']} aktual tertunda."
        )
        return 0

    print(f"Pemantauan gagal: {run.failure_reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
