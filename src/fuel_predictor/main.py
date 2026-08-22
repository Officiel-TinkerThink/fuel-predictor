from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from fuel_predictor.application.actual_fuel import GetPredictionPerformance, RecordActualFuel
from fuel_predictor.application.baseline_predictions import (
    GenerateFuelPrediction,
    TrainBaselineCandidate,
)
from fuel_predictor.application.bulk_actual_fuel import BulkActualFuel
from fuel_predictor.application.bulk_operation_predictions import BulkOperationPrediction
from fuel_predictor.application.daily_operations import CreateDailyOperation, GetDailyOperation
from fuel_predictor.application.historical_datasets import (
    GetDatasetValidOperations,
    ImportHistoricalDataset,
)
from fuel_predictor.application.model_lifecycle import (
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    PromoteCandidateModel,
)
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.application.routing import RoutingProvider, UnavailableRoutingProvider
from fuel_predictor.configuration import ApplicationSettings
from fuel_predictor.delivery.form import build_form_router
from fuel_predictor.delivery.http import build_router, register_error_handlers
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.evidently_drift import EvidentlyFeatureDriftAnalyzer
from fuel_predictor.infrastructure.google_maps_routing import GoogleMapsRoutesProvider
from fuel_predictor.infrastructure.historical_source_reader import (
    SpreadsheetHistoricalDatasetSourceReader,
)
from fuel_predictor.infrastructure.mlflow_baseline_models import MlflowBaselineModelStore
from fuel_predictor.infrastructure.sqlalchemy_actual_fuel import SqlAlchemyActualFuelRepository
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import (
    SqlAlchemyDailyOperationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_historical_datasets import (
    SqlAlchemyHistoricalDatasetRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_monitoring import SqlAlchemyMonitoringRepository
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository


def create_app(
    database_path: Path | None = None,
    database_url: str | None = None,
    routing_provider: RoutingProvider | None = None,
) -> FastAPI:
    if database_path is not None and database_url is not None:
        raise ValueError("Pilih salah satu: database_path atau database_url.")

    uses_test_schema = database_path is not None
    resolved_database_url = database_url or _database_url_for_path(database_path)
    engine = build_engine(resolved_database_url)
    if uses_test_schema:
        create_schema_for_tests(engine)
    session_factory = build_session_factory(engine)
    repository = SqlAlchemyDailyOperationRepository(session_factory)
    historical_dataset_repository = SqlAlchemyHistoricalDatasetRepository(session_factory)
    prediction_repository = SqlAlchemyPredictionRepository(session_factory)
    actual_fuel_repository = SqlAlchemyActualFuelRepository(session_factory)
    monitoring_repository = SqlAlchemyMonitoringRepository(session_factory)
    settings = ApplicationSettings()
    resolved_routing_provider = routing_provider or _routing_provider_from_settings(settings)
    create_daily_operation = CreateDailyOperation(repository, resolved_routing_provider)
    get_daily_operation = GetDailyOperation(repository)
    import_historical_dataset = ImportHistoricalDataset(
        SpreadsheetHistoricalDatasetSourceReader(), historical_dataset_repository
    )
    get_dataset_valid_operations = GetDatasetValidOperations(historical_dataset_repository)
    if settings.mlflow_tracking_uri is not None:
        model_store = MlflowBaselineModelStore(settings.mlflow_tracking_uri)
    else:
        if database_path is None:
            tracking_directory = settings.mlflow_tracking_directory
        else:
            tracking_directory = database_path.parent / "mlruns"
        model_store = MlflowBaselineModelStore.local(tracking_directory)
    train_baseline_candidate = TrainBaselineCandidate(
        historical_dataset_repository, model_store, prediction_repository
    )
    generate_fuel_prediction = GenerateFuelPrediction(
        repository,
        prediction_repository,
        model_store,
        prediction_repository,
        settings.initial_safety_margin_liters,
    )
    bulk_operation_prediction = BulkOperationPrediction(
        SpreadsheetHistoricalDatasetSourceReader(),
        create_daily_operation,
        generate_fuel_prediction,
        repository,
    )
    record_actual_fuel = RecordActualFuel(repository, actual_fuel_repository)
    bulk_actual_fuel = BulkActualFuel(
        SpreadsheetHistoricalDatasetSourceReader(), record_actual_fuel
    )
    get_prediction_performance = GetPredictionPerformance(actual_fuel_repository)
    promote_candidate_model = PromoteCandidateModel(prediction_repository, prediction_repository)
    get_candidate_model_comparison = GetCandidateModelComparison(
        prediction_repository, actual_fuel_repository, model_store
    )
    get_model_governance_dashboard = GetModelGovernanceDashboard(
        prediction_repository,
        actual_fuel_repository,
        model_store,
        settings.max_active_model_mae_liters,
    )
    get_monitoring_dashboard = GetMonitoringDashboard(
        monitoring_repository,
        prediction_repository,
        monitoring_repository,
        EvidentlyFeatureDriftAnalyzer(),
        settings.missing_actual_after_days,
        settings.monitoring_drift_share_threshold,
        settings.monitoring_rolling_error_window,
        settings.max_active_model_mae_liters,
        settings.monitoring_min_matched_outcomes,
    )

    @asynccontextmanager
    async def application_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if isinstance(resolved_routing_provider, GoogleMapsRoutesProvider):
                resolved_routing_provider.close()
            engine.dispose()

    app = FastAPI(
        title="Perencana Operasi Harian",
        version="1.0.0",
        lifespan=application_lifespan,
    )
    register_error_handlers(app)
    app.include_router(
        build_router(
            create_daily_operation,
            get_daily_operation,
            import_historical_dataset,
            get_dataset_valid_operations,
            train_baseline_candidate,
            generate_fuel_prediction,
            bulk_operation_prediction,
            record_actual_fuel,
            bulk_actual_fuel,
            get_prediction_performance,
            promote_candidate_model,
            get_candidate_model_comparison,
            get_model_governance_dashboard,
            get_monitoring_dashboard,
        )
    )
    app.include_router(
        build_form_router(
            create_daily_operation,
            import_historical_dataset,
            train_baseline_candidate,
            generate_fuel_prediction,
            bulk_operation_prediction,
            record_actual_fuel,
            bulk_actual_fuel,
            get_prediction_performance,
            promote_candidate_model,
            get_candidate_model_comparison,
            get_model_governance_dashboard,
            get_monitoring_dashboard,
        )
    )
    return app


def _database_url_for_path(database_path: Path | None) -> str:
    if database_path is None:
        return ApplicationSettings().database_url
    return f"sqlite+pysqlite:///{database_path.resolve().as_posix()}"


def _routing_provider_from_settings(settings: ApplicationSettings) -> RoutingProvider:
    if settings.google_maps_api_key is None:
        return UnavailableRoutingProvider()
    return GoogleMapsRoutesProvider(settings.google_maps_api_key.get_secret_value())


app = create_app()
