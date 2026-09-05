"""Command-line entry points for scheduled work (Phase 3).

    python -m fuel_predictor monitor

Run by the host scheduler or a small Compose job. Exits non-zero when a run
fails so the scheduler notices, which is the signal the plan's failed-run
alerting depends on — a job that always exits zero cannot be monitored.
"""

import argparse
import sys
from collections.abc import Sequence
from typing import Any

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

    backup = subcommands.add_parser(
        "record-backup",
        help="Catat hasil satu percobaan pencadangan (dipanggil oleh skrip cadangan).",
    )
    backup.add_argument("--outcome", choices=("succeeded", "failed"), required=True)
    backup.add_argument(
        "--destination", required=True, help="Tujuan salinan, misalnya remote:bucket/path."
    )
    backup.add_argument("--size-bytes", type=int, default=None)
    backup.add_argument("--failure-reason", default=None)

    locations = subcommands.add_parser(
        "import-locations",
        help="Muat ulang katalog lokasi dari ekspor sheet 'Data Lokasi'.",
    )
    locations.add_argument(
        "--source",
        default=None,
        help="Berkas CSV lokasi. Bawaan: ekspor yang ikut dipaketkan bersama aplikasi.",
    )

    vehicles = subcommands.add_parser(
        "import-vehicles",
        help="Muat ulang katalog kendaraan dari ekspor sheet 'Dim_Kendaraan'.",
    )
    vehicles.add_argument(
        "--source",
        default=None,
        help="Berkas CSV kendaraan. Bawaan: ekspor yang ikut dipaketkan bersama aplikasi.",
    )

    seed = subcommands.add_parser(
        "seed-demo",
        help="Isi basis data kosong dengan katalog, riwayat contoh, dan satu model aktif.",
    )
    seed.add_argument(
        "--force",
        action="store_true",
        help="Ulangi meski sudah ada model aktif. Tanpa ini perintah berhenti agar aman.",
    )

    prune = subcommands.add_parser(
        "prune-packages",
        help="Hapus paket model lama yang bukan sasaran rollback. Bawaan: hanya menampilkan.",
    )
    prune.add_argument(
        "--apply",
        action="store_true",
        help="Benar-benar menghapus. Tanpa ini hanya rencananya yang ditampilkan.",
    )
    prune.add_argument("--keep-retired", type=int, default=3)

    arguments = parser.parse_args(argv)
    if arguments.command == "monitor":
        return _run_monitoring(arguments.trigger)
    if arguments.command == "import-locations":
        return _import_locations(arguments.source)
    if arguments.command == "import-vehicles":
        return _import_vehicles(arguments.source)
    if arguments.command == "seed-demo":
        return _seed_demo(force=arguments.force)
    if arguments.command == "prune-packages":
        return _prune_packages(apply=arguments.apply, keep_retired=arguments.keep_retired)
    if arguments.command == "record-backup":
        return _record_backup(
            outcome=arguments.outcome,
            destination=arguments.destination,
            size_bytes=arguments.size_bytes,
            failure_reason=arguments.failure_reason,
        )
    return 2


def _import_locations(source: str | None) -> int:
    """Replace the location catalog with what the sheet export holds."""
    from pathlib import Path

    from fuel_predictor.infrastructure.packaged_location_catalog import PackagedLocationCatalog
    from fuel_predictor.infrastructure.sqlalchemy_locations import SqlAlchemyLocationRepository

    settings = ApplicationSettings()
    try:
        catalog = PackagedLocationCatalog(Path(source) if source else None)
        factory = build_session_factory(build_engine(settings.database_url))
        imported = SqlAlchemyLocationRepository(factory).replace_all(catalog.options())
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        print(f"Impor lokasi gagal: {error}", file=sys.stderr)
        return 1

    print(f"{imported} lokasi tersimpan di basis data.")
    return 0


def _import_vehicles(source: str | None) -> int:
    """Replace the fleet catalog with what the sheet export holds."""
    from pathlib import Path

    from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
    from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository

    settings = ApplicationSettings()
    try:
        catalog = PackagedVehicleCatalog(Path(source) if source else None)
        factory = build_session_factory(build_engine(settings.database_url))
        imported = SqlAlchemyVehicleRepository(factory).replace_all(catalog.options())
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        print(f"Impor kendaraan gagal: {error}", file=sys.stderr)
        return 1

    print(f"{imported} kendaraan tersimpan di basis data.")
    return 0


def _seed_demo(force: bool) -> int:
    """Bring an empty database to the point where a prediction can be made.

    A fresh deployment has a schema and nothing else: no locations to pick, no
    fleet, no history, and so no model — the first thing a visitor meets is a
    form whose dropdowns are empty and a prediction that cannot be produced.
    This walks the same path an operator would take through the UI, in the same
    order, so what it leaves behind is ordinary data rather than a special
    "demo mode" the application would have to know about.
    """
    from importlib import resources

    from fuel_predictor.application.baseline_predictions import TrainBaselineCandidate
    from fuel_predictor.application.historical_datasets import ImportHistoricalDataset
    from fuel_predictor.application.model_lifecycle import PromoteCandidateModel
    from fuel_predictor.application.prediction_features import feature_values
    from fuel_predictor.infrastructure.historical_source_reader import (
        SpreadsheetHistoricalDatasetSourceReader,
    )
    from fuel_predictor.infrastructure.mlflow_baseline_models import MlflowBaselineModelStore
    from fuel_predictor.infrastructure.packaged_location_catalog import PackagedLocationCatalog
    from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
    from fuel_predictor.infrastructure.sqlalchemy_historical_datasets import (
        SqlAlchemyHistoricalDatasetRepository,
    )
    from fuel_predictor.infrastructure.sqlalchemy_locations import SqlAlchemyLocationRepository
    from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository

    settings = ApplicationSettings()
    try:
        factory = build_session_factory(build_engine(settings.database_url))
        predictions = SqlAlchemyPredictionRepository(factory)

        # Seeding twice would leave a second dataset version and a second model
        # behind, so the safe default is to stop once the work is already done.
        if predictions.get_active() is not None and not force:
            print("Basis data sudah berisi model aktif. Tidak ada yang perlu diisi.")
            print("Jalankan ulang dengan --force bila memang ingin mengulang.")
            return 0

        vehicles = SqlAlchemyVehicleRepository(factory)
        location_count = SqlAlchemyLocationRepository(factory).replace_all(
            PackagedLocationCatalog().options()
        )
        vehicle_count = vehicles.replace_all(PackagedVehicleCatalog().options())
        print(f"  {location_count} lokasi dan {vehicle_count} kendaraan dimuat.")

        historical = SqlAlchemyHistoricalDatasetRepository(factory)
        demo_history = resources.files("fuel_predictor") / "examples" / "riwayat-angber-demo.csv"
        imported = ImportHistoricalDataset(
            SpreadsheetHistoricalDatasetSourceReader(),
            historical,
            vehicle_catalog=vehicles,
        ).execute("riwayat-angber-demo.csv", demo_history.read_bytes())
        dataset = imported.dataset_version
        print(
            f"  Riwayat {dataset.dataset_version_id} diimpor: "
            f"{len(imported.valid_operations)} baris valid."
        )

        # The tracking URI wins when set, exactly as the application resolves
        # it, so the seeded model lands in the store the app will read from.
        if settings.mlflow_tracking_uri is not None:
            model_store = MlflowBaselineModelStore(settings.mlflow_tracking_uri)
        else:
            model_store = MlflowBaselineModelStore.local(settings.mlflow_tracking_directory)
        candidate = TrainBaselineCandidate(historical, model_store, predictions).execute(
            dataset.dataset_version_id
        )
        print(f"  Kandidat {candidate.model_version_id} dilatih.")

        promoted = PromoteCandidateModel(predictions, predictions).execute(
            candidate.model_version_id
        )

        # Read the model back before calling the database ready. Training only
        # proves it could be written; serving needs it fetched again, possibly
        # from a different machine than the one that trained it. When those two
        # are wired up wrongly the training step still reports success and the
        # first prediction is what fails -- in front of whoever we handed the
        # demo to.
        sample = feature_values(imported.valid_operations[0].operation)
        litres = model_store.predict(promoted.artifact_uri, sample)
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        print(f"Pengisian data awal gagal: {error}", file=sys.stderr)
        return 1

    print(f"  Model {promoted.model_version_id} dipromosikan menjadi aktif.")
    print(f"  Model dibaca ulang dan menghasilkan {litres:.1f} L untuk satu baris contoh.")
    print("Basis data siap dipakai: buka /prediksi dan buat satu operasi harian.")
    return 0


def _prune_packages(apply: bool, keep_retired: int) -> int:
    """Report the retention plan, and act on it only when asked.

    Dry-run by default because the failure mode is asymmetric: keeping too much
    wastes disk, while deleting a rollback target removes the recovery path and
    nobody finds out until the day they need it.
    """
    from fuel_predictor.application.package_retention import PruneRetainedPackages
    from fuel_predictor.infrastructure.model_artifact_store import FilesystemModelArtifactStore
    from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository

    settings = ApplicationSettings()
    try:
        factory = build_session_factory(build_engine(settings.database_url))
        plan = PruneRetainedPackages(
            models=SqlAlchemyPredictionRepository(factory),
            store=FilesystemModelArtifactStore(root=settings.model_artifact_directory),
            keep_retired=keep_retired,
        ).execute(dry_run=not apply)
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        print(f"Pemangkasan paket gagal: {error}", file=sys.stderr)
        return 1

    for model_version, reason in plan.reasons.items():
        print(f"  simpan  {model_version}  ({reason})")
    for model_version in plan.prune:
        print(f"  {'hapus  ' if apply else 'akan dihapus'}  {model_version}")
    if not plan.prune:
        print("Tidak ada paket yang perlu dihapus.")
    elif not apply:
        print("")
        print(f"{len(plan.prune)} paket dapat dihapus. Jalankan ulang dengan --apply.")
    return 0


def _record_backup(
    outcome: str, destination: str, size_bytes: int | None, failure_reason: str | None
) -> int:
    """Record what the backup script actually did.

    Outcomes are reported by the job rather than inferred: the application
    cannot see whether an off-VM upload succeeded, and guessing would produce a
    reassuring dashboard with no basis behind it.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from fuel_predictor.application.monitoring_runs import BackupRun, RunOutcome
    from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
        SqlAlchemyBackupRunRepository,
    )

    settings = ApplicationSettings()
    try:
        factory = build_session_factory(build_engine(settings.database_url))
        SqlAlchemyBackupRunRepository(factory).add(
            BackupRun(
                run_id=f"BAK-{uuid4().hex[:20]}",
                finished_at=datetime.now(UTC),
                outcome=RunOutcome.SUCCEEDED if outcome == "succeeded" else RunOutcome.FAILED,
                destination=destination,
                size_bytes=size_bytes,
                failure_reason=failure_reason,
            )
        )
    except Exception as error:  # noqa: BLE001 - the operator needs a readable message
        print(
            "Hasil pencadangan gagal dicatat: basis data tidak dapat dihubungi. "
            f"Detail: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Hasil pencadangan dicatat: {outcome}.")
    # A recorded failure is still a successful recording. The backup script's
    # own exit code is what tells the scheduler the backup failed; making this
    # command fail too would report the same problem twice and hide whether
    # recording itself worked.
    return 0


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
        _deliver_alerts(settings, monitoring_repository, session_factory)
        return 0

    print(f"Pemantauan gagal: {run.failure_reason}", file=sys.stderr)
    return 1


def _deliver_alerts(
    settings: ApplicationSettings, monitoring_repository: Any, factory: Any
) -> None:
    """Tell someone, if a channel is configured and the picture changed.

    Deliberately does not affect the exit code. Monitoring itself succeeded;
    turning a notification problem into a failed monitoring run would make the
    scheduler report the wrong thing. The outcome is printed instead, and an
    unconfigured channel is stated plainly rather than passing silently — "no
    alerts were sent" and "nobody is listening" must not look the same.
    """
    from datetime import UTC, datetime

    from fuel_predictor.application.alert_delivery import DeliverMonitoringAlerts
    from fuel_predictor.infrastructure.alert_notifiers import build_notifier
    from fuel_predictor.infrastructure.sqlalchemy_alert_delivery import (
        SqlAlchemyAlertDeliveryStore,
    )

    try:
        result = DeliverMonitoringAlerts(
            notifier=build_notifier(settings),
            store=SqlAlchemyAlertDeliveryStore(factory),
        ).execute(monitoring_repository.list_active_alerts(), datetime.now(UTC))
    except Exception as error:  # noqa: BLE001 - never fails the monitoring run
        print(f"Pengiriman peringatan gagal: {error}", file=sys.stderr)
        return

    if result.sent:
        print(
            f"Peringatan terkirim: {len(result.new_alerts)} baru, "
            f"{len(result.changed_alerts)} berubah, {len(result.resolved_alerts)} teratasi."
        )
    elif result.error is not None:
        print(f"Peringatan tidak terkirim ({result.reason}): {result.error}", file=sys.stderr)
    elif result.new_alerts or result.changed_alerts or result.resolved_alerts:
        print(f"Peringatan tidak terkirim: {result.reason}.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
