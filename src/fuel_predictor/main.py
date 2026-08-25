from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_bytes
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fuel_predictor.application.actual_fuel import GetPredictionPerformance, RecordActualFuel
from fuel_predictor.application.agent_credentials import (
    IssueAgentCredential,
    ListAgentClients,
    ResolveAgentCredential,
    RevokeAgentCredential,
)
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
from fuel_predictor.application.identity import (
    CreateUser,
    EnsureBootstrapAdministrator,
    ListAuditRecords,
    ListUsers,
    RecordAuditEvent,
    ResolveSession,
    SignIn,
    SignOut,
)
from fuel_predictor.application.model_activation import (
    ActiveModelHolder,
    answers_a_representative_case,
)
from fuel_predictor.application.model_lifecycle import (
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    PromoteCandidateModel,
)
from fuel_predictor.application.model_package_ingestion import (
    ModelPackageArchiveLimits,
    ParseModelPackageManifest,
    ParseReferenceStatistics,
    ParseSmokeTests,
)
from fuel_predictor.application.model_package_validation import ValidateModelPackage
from fuel_predictor.application.model_promotion_policy import (
    EvaluateCandidateAgainstPolicy,
    PromotionPolicy,
)
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.application.retained_package_activation import (
    ActivateRetainedModelPackage,
    RegisterIngestedPackage,
)
from fuel_predictor.application.routing import RoutingProvider, UnavailableRoutingProvider
from fuel_predictor.configuration import ApplicationSettings
from fuel_predictor.delivery.actual_fuel_pages import build_actual_fuel_pages_router
from fuel_predictor.delivery.agent_pages import build_agent_pages_router
from fuel_predictor.delivery.authentication import (
    build_authentication_router,
    register_identity_error_handlers,
)
from fuel_predictor.delivery.bulk_prediction_pages import build_bulk_prediction_pages_router
from fuel_predictor.delivery.dashboard import build_dashboard_router
from fuel_predictor.delivery.historical_dataset_pages import (
    build_historical_dataset_pages_router,
)
from fuel_predictor.delivery.http import build_router, register_error_handlers
from fuel_predictor.delivery.mcp_privileged import ConfirmationTokens, build_privileged_tools
from fuel_predictor.delivery.mcp_routes import build_mcp_router
from fuel_predictor.delivery.mcp_server import (
    McpRequestHandler,
    McpToolRegistry,
    build_registry,
)
from fuel_predictor.delivery.model_governance_pages import build_model_governance_pages_router
from fuel_predictor.delivery.model_upload_pages import build_model_upload_pages_router
from fuel_predictor.delivery.monitoring_pages import build_monitoring_pages_router
from fuel_predictor.delivery.prediction_pages import build_prediction_pages_router
from fuel_predictor.delivery.rendering import STATIC_DIRECTORY
from fuel_predictor.delivery.security import (
    SecurityGuard,
    install_session_middleware,
    register_security_error_handlers,
)
from fuel_predictor.domain.identity import AuditOutcome
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
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    REFERENCE_STATISTICS_SCHEMA,
    SMOKE_TESTS_SCHEMA,
    JsonSchemaManifestValidator,
    JsonSchemaValidator,
)
from fuel_predictor.infrastructure.mlflow_baseline_models import MlflowBaselineModelStore
from fuel_predictor.infrastructure.model_artifact_loader import build_loader
from fuel_predictor.infrastructure.model_artifact_store import FilesystemModelArtifactStore
from fuel_predictor.infrastructure.password_hashing import ScryptPasswordHasher
from fuel_predictor.infrastructure.sqlalchemy_actual_fuel import SqlAlchemyActualFuelRepository
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import (
    SqlAlchemyDailyOperationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_historical_datasets import (
    SqlAlchemyHistoricalDatasetRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_identity import (
    SqlAlchemyAgentClientRepository,
    SqlAlchemyAuditRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_model_package_records import (
    SqlAlchemyModelPackageValidationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_monitoring import SqlAlchemyMonitoringRepository
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyBackupRunRepository,
    SqlAlchemyMonitoringRunRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository
from fuel_predictor.infrastructure.system_memory_probe import SystemMemoryProbe
from fuel_predictor.infrastructure.zip_model_package_archive import ZipModelPackageArchiveReader

# One representative operation the post-activation health check asks the
# newly-swapped model to answer. Mid-range values on purpose: a case at the
# edge of the training distribution would fail for reasons that say nothing
# about whether the swap worked.
_HEALTH_CHECK_FEATURES: dict[str, str | float] = {
    "vehicle_category": "ANGBER",
    "activity_mode": "transport",
    "distance_source": "manual",
    "total_distance_km": 30.0,
    "lifting_hours": 0.0,
}


def _rollback_recorder(record_audit: RecordAuditEvent) -> Any:
    """Adapt the audit use case to the rollback recorder's keyword shape.

    Rollback records the *intent* — who, which target, and why — before the
    change is attempted, so the decision survives an attempt that then fails.
    """

    def record(
        *, target_version_id: str, previous_version_id: str | None, actor: str, reason: str
    ) -> None:
        record_audit.execute(
            actor=actor,
            action="model_rollback_requested",
            outcome=AuditOutcome.SUCCEEDED,
            subject=target_version_id,
            details={"previous_version_id": previous_version_id, "reason": reason[:500]},
        )

    return record


def create_app(
    database_path: Path | None = None,
    database_url: str | None = None,
    routing_provider: RoutingProvider | None = None,
    bootstrap_administrator: tuple[str, str] | None = None,
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
    user_repository = SqlAlchemyUserRepository(session_factory)
    session_repository = SqlAlchemySessionRepository(session_factory)
    audit_repository = SqlAlchemyAuditRepository(session_factory)
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
    # One holder, shared by the serving path and the activation path. Until a
    # package is activated it stays empty and prediction falls back to the
    # MLflow store, which is what ADR 0011 requires.
    active_model_holder = ActiveModelHolder()
    generate_fuel_prediction = GenerateFuelPrediction(
        repository,
        prediction_repository,
        model_store,
        prediction_repository,
        settings.initial_safety_margin_liters,
        holder=active_model_holder,
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
    password_hasher = ScryptPasswordHasher()
    record_audit = RecordAuditEvent(audit_repository)
    sign_in = SignIn(user_repository, session_repository, password_hasher, record_audit)
    sign_out = SignOut(session_repository, record_audit)
    resolve_session = ResolveSession(user_repository, session_repository)
    create_user = CreateUser(user_repository, password_hasher, record_audit)
    list_users = ListUsers(user_repository)
    list_audit_records = ListAuditRecords(audit_repository)
    ensure_bootstrap_administrator = EnsureBootstrapAdministrator(user_repository, create_user)
    resolved_bootstrap_administrator = bootstrap_administrator or (
        (settings.bootstrap_admin_username, settings.bootstrap_admin_password.get_secret_value())
        if settings.bootstrap_admin_username and settings.bootstrap_admin_password
        else None
    )
    if resolved_bootstrap_administrator is not None:
        ensure_bootstrap_administrator.execute(*resolved_bootstrap_administrator)
    monitoring_run_repository = SqlAlchemyMonitoringRunRepository(session_factory)
    backup_run_repository = SqlAlchemyBackupRunRepository(session_factory)
    validation_records = SqlAlchemyModelPackageValidationRepository(session_factory)
    artifact_store = FilesystemModelArtifactStore(root=settings.model_artifact_directory)
    parse_model_package_manifest = ParseModelPackageManifest(
        schema_validator=JsonSchemaManifestValidator(),
        supported_feature_contract_versions=frozenset(
            _split_setting(settings.supported_feature_contract_versions)
        ),
        supported_runtime_compatibility_versions=frozenset(
            _split_setting(settings.supported_runtime_compatibility_versions)
        ),
    )
    parse_package_smoke_tests = ParseSmokeTests(
        schema_validator=JsonSchemaValidator(SMOKE_TESTS_SCHEMA)
    )
    validate_package = ValidateModelPackage(
        archive_reader=ZipModelPackageArchiveReader(
            ModelPackageArchiveLimits(
                max_archive_bytes=settings.model_package_max_archive_bytes,
                max_extracted_bytes=settings.model_package_max_extracted_bytes,
                max_member_count=settings.model_package_max_member_count,
                max_compression_ratio=settings.model_package_max_compression_ratio,
            )
        ),
        parse_manifest=parse_model_package_manifest,
        parse_reference_statistics=ParseReferenceStatistics(
            schema_validator=JsonSchemaValidator(REFERENCE_STATISTICS_SCHEMA)
        ),
        parse_smoke_tests=parse_package_smoke_tests,
        evaluate_policy=EvaluateCandidateAgainstPolicy(
            policy=PromotionPolicy(
                max_mae_liters=settings.max_active_model_mae_liters,
                max_mae_regression_ratio=settings.promotion_max_mae_regression_ratio,
                minimum_test_set_size=settings.promotion_minimum_test_set_size,
            )
        ),
        build_artifact_loader=build_loader,
    )
    register_ingested_package = RegisterIngestedPackage(models=prediction_repository)
    activate_retained_package = ActivateRetainedModelPackage(
        store=artifact_store,
        models=prediction_repository,
        parse_manifest=parse_model_package_manifest,
        parse_smoke_tests=parse_package_smoke_tests,
        build_artifact_loader=build_loader,
        holder=active_model_holder,
        repository=prediction_repository,
        memory_probe=SystemMemoryProbe(),
        health_check=answers_a_representative_case(_HEALTH_CHECK_FEATURES),
        record_rollback=_rollback_recorder(record_audit),
    )
    agent_client_repository = SqlAlchemyAgentClientRepository(session_factory)
    issue_agent_credential = IssueAgentCredential(agent_client_repository, record_audit)
    revoke_agent_credential = RevokeAgentCredential(agent_client_repository, record_audit)
    list_agent_clients = ListAgentClients(agent_client_repository)
    mcp_registry = build_registry(
        generate_prediction=generate_fuel_prediction,
        create_operation=create_daily_operation,
        monitoring_dashboard=get_monitoring_dashboard,
        prediction_performance=get_prediction_performance,
        model_reader=prediction_repository,
        monitoring_runs=monitoring_run_repository,
    )
    if settings.mcp_privileged_tools_enabled:
        # Off by default. The plan gates validate/activate/rollback on the
        # read-only surface proving itself in production and on a security
        # review, so enabling them is an operator's explicit decision.
        mcp_registry = McpToolRegistry(
            tools=mcp_registry.tools
            + build_privileged_tools(
                activate_retained_package=activate_retained_package,
                rollback_model_version=lambda version_id, expected, reason: (
                    activate_retained_package.rollback(
                        target_version_id=version_id,
                        expected_active_version_id=expected,
                        actor="mcp-agent",
                        reason=reason,
                    )
                ),
                model_reader=prediction_repository,
                validate_retained_package=activate_retained_package.inspect,
                tokens=ConfirmationTokens(secret=token_bytes(32)),
            )
        )
    mcp_handler = McpRequestHandler(
        registry=mcp_registry,
        resolve_credential=ResolveAgentCredential(agent_client_repository),
        record_audit=record_audit,
    )
    guard = SecurityGuard()

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
    register_identity_error_handlers(app)
    register_security_error_handlers(app)
    install_session_middleware(app, resolve_session)
    app.mount("/statis", StaticFiles(directory=STATIC_DIRECTORY), name="statis")
    app.include_router(
        build_authentication_router(
            sign_in,
            sign_out,
            create_user,
            list_users,
            list_audit_records,
            guard,
            cookies_require_https=settings.session_cookies_require_https,
        )
    )
    app.include_router(
        build_dashboard_router(
            get_monitoring_dashboard,
            get_model_governance_dashboard,
            create_user,
            list_users,
            list_audit_records,
            guard,
            monitoring_run_repository,
            backup_run_repository,
            settings.monitoring_stale_after_hours,
        )
    )
    app.include_router(
        build_prediction_pages_router(
            create_daily_operation,
            generate_fuel_prediction,
            guard,
        )
    )
    app.include_router(
        build_bulk_prediction_pages_router(
            bulk_operation_prediction,
            guard,
        )
    )
    app.include_router(
        build_actual_fuel_pages_router(
            record_actual_fuel,
            bulk_actual_fuel,
            guard,
        )
    )
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
        build_historical_dataset_pages_router(
            import_historical_dataset,
            train_baseline_candidate,
            guard,
        )
    )
    app.include_router(
        build_model_governance_pages_router(
            promote_candidate_model,
            activate_retained_package,
            get_candidate_model_comparison,
            get_model_governance_dashboard,
            guard,
        )
    )
    app.include_router(
        build_model_upload_pages_router(
            validate_package,
            validation_records,
            artifact_store,
            register_ingested_package,
            guard,
        )
    )
    app.include_router(build_mcp_router(mcp_handler, server_version="1.0.0"))
    app.include_router(
        build_agent_pages_router(
            issue_agent_credential,
            revoke_agent_credential,
            list_agent_clients,
            guard,
        )
    )
    app.include_router(
        build_monitoring_pages_router(
            get_monitoring_dashboard,
            get_prediction_performance,
            guard,
            monitoring_run_repository,
            backup_run_repository,
            settings.monitoring_stale_after_hours,
        )
    )
    return app


def _split_setting(value: str) -> tuple[str, ...]:
    """Comma-separated settings, since pydantic-settings reads env vars as strings."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _database_url_for_path(database_path: Path | None) -> str:
    if database_path is None:
        return ApplicationSettings().database_url
    return f"sqlite+pysqlite:///{database_path.resolve().as_posix()}"


def _routing_provider_from_settings(settings: ApplicationSettings) -> RoutingProvider:
    if settings.google_maps_api_key is None:
        return UnavailableRoutingProvider()
    return GoogleMapsRoutesProvider(settings.google_maps_api_key.get_secret_value())


app = create_app()
