from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_bytes
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fuel_predictor.application.actual_fuel import (
    GetPredictionPerformance,
    ListOperationsAwaitingActualFuel,
    RecordActualFuel,
)
from fuel_predictor.application.agent_credentials import (
    IssueAgentCredential,
    ListAgentClients,
    ResolveAgentCredential,
    RevokeAgentCredential,
)
from fuel_predictor.application.agent_grants import (
    DeleteAgentGrant,
    IssueAuthorizationCode,
    ListAgentGrants,
    RedeemAuthorizationCode,
    RefreshGrant,
    RegisterAgentClient,
    RenameAgentGrant,
    ResolveAgentBearer,
    ResolveGrantAccessToken,
    RevokeAgentGrant,
    RevokeGrantByToken,
    ValidateAuthorizationRequest,
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
    ChangeOwnPassword,
    ChangePassword,
    CreateUser,
    EnsureBootstrapAdministrator,
    ListAuditRecords,
    ListUsers,
    PasswordResetMailer,
    RecordAuditEvent,
    RequestPasswordReset,
    ResetPasswordWithToken,
    ResolveSession,
    SetUserActivation,
    SignIn,
    SignOut,
)
from fuel_predictor.application.locations import LocationCatalog
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
from fuel_predictor.application.prediction_features import feature_values
from fuel_predictor.application.prediction_history import (
    GetLatestPrediction,
    ListRecentPredictions,
)
from fuel_predictor.application.retained_package_activation import (
    ActivateRetainedModelPackage,
    RegisterIngestedPackage,
)
from fuel_predictor.application.routing import (
    RoutePreviewProvider,
    RoutingProvider,
    UnavailableRoutingProvider,
)
from fuel_predictor.application.similar_operations import FindSimilarOperations
from fuel_predictor.application.user_directory import (
    GetUserDetail,
    GetUserDirectory,
    UpdateUserProfile,
)
from fuel_predictor.application.vehicles import VehicleCatalog, VehicleLineage
from fuel_predictor.configuration import ApplicationSettings
from fuel_predictor.delivery.actual_fuel_pages import build_actual_fuel_pages_router
from fuel_predictor.delivery.agent_pages import build_agent_pages_router
from fuel_predictor.delivery.authentication import (
    build_authentication_router,
    register_identity_error_handlers,
)
from fuel_predictor.delivery.bulk_prediction_pages import build_bulk_prediction_pages_router
from fuel_predictor.delivery.dashboard import build_dashboard_router
from fuel_predictor.delivery.events import ImportantEvents
from fuel_predictor.delivery.fleet_pages import build_fleet_pages_router
from fuel_predictor.delivery.health import build_health_router
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
from fuel_predictor.delivery.oauth_routes import build_oauth_router
from fuel_predictor.delivery.prediction_pages import build_prediction_pages_router
from fuel_predictor.delivery.rendering import STATIC_DIRECTORY, configure_site_timezone
from fuel_predictor.delivery.security import (
    SecurityGuard,
    install_session_middleware,
    register_security_error_handlers,
)
from fuel_predictor.delivery.user_pages import build_user_pages_router
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.identity import AuditOutcome
from fuel_predictor.infrastructure.alert_notifiers import (
    build_notifier,
    build_password_reset_mailer,
)
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
from fuel_predictor.infrastructure.sqlalchemy_agent_grants import (
    SqlAlchemyAgentGrantRepository,
    SqlAlchemyAgentRegistrationRepository,
    SqlAlchemyAuthorizationCodeRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import (
    SqlAlchemyDailyOperationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_historical_datasets import (
    SqlAlchemyHistoricalDatasetRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_identity import (
    SqlAlchemyAgentClientRepository,
    SqlAlchemyAuditRepository,
    SqlAlchemyPasswordResetTokenRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_locations import SqlAlchemyLocationRepository
from fuel_predictor.infrastructure.sqlalchemy_model_package_records import (
    SqlAlchemyModelPackageValidationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_monitoring import SqlAlchemyMonitoringRepository
from fuel_predictor.infrastructure.sqlalchemy_monitoring_runs import (
    SqlAlchemyBackupRunRepository,
    SqlAlchemyMonitoringRunRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_prediction_history import (
    SqlAlchemyPredictionHistoryRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository
from fuel_predictor.infrastructure.sqlalchemy_similar_operations import (
    SqlAlchemyHistoricalOperationSource,
)
from fuel_predictor.infrastructure.sqlalchemy_user_activity import SqlAlchemyUserActivityRepository
from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository
from fuel_predictor.infrastructure.system_memory_probe import SystemMemoryProbe
from fuel_predictor.infrastructure.zip_model_package_archive import ZipModelPackageArchiveReader

# One representative operation the post-activation health check asks the
# newly-swapped model to answer. Mid-range values on purpose: a case at the
# edge of the training distribution would fail for reasons that say nothing
# about whether the swap worked. Built through the feature contract rather
# than written out: a hand-written dict stayed on baseline-v1 when `vehicle`
# became a feature, and every baseline-v2 package then failed this check.
HEALTH_CHECK_FEATURES: dict[str, str | float] = feature_values(
    DailyOperation(
        operation_id="HEALTH-CHECK",
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
    ),
    VehicleLineage.unknown(),
)


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
    # A test seam like `routing_provider`: lets a test put the form in its
    # routing-provider shape (a map, no up-front distance) without a Maps key.
    route_preview: RoutePreviewProvider | None = None,
    location_catalog: LocationCatalog | None = None,
    vehicle_catalog: VehicleCatalog | None = None,
    bootstrap_administrator: tuple[str, str] | None = None,
    allow_unprovisioned_access: bool | None = None,
    public_url: str | None = None,
    password_reset_mailer: PasswordResetMailer | None = None,
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
    resolved_public_url = settings.public_url if public_url is None else public_url
    resolved_location_catalog = location_catalog or SqlAlchemyLocationRepository(session_factory)
    resolved_vehicle_catalog = vehicle_catalog or SqlAlchemyVehicleRepository(session_factory)
    # One adapter serves both roles when a key is configured: it computes the
    # saved distance and draws the route the planner previews. An empty key is
    # treated as no key, so a blanked-out setting disables it cleanly.
    maps_api_key = (
        settings.google_maps_api_key.get_secret_value() if settings.google_maps_api_key else None
    )
    maps_provider = (
        GoogleMapsRoutesProvider(maps_api_key, location_catalog=resolved_location_catalog)
        if maps_api_key
        else None
    )
    resolved_routing_provider = routing_provider or maps_provider or UnavailableRoutingProvider()
    resolved_route_preview = route_preview or maps_provider
    configure_site_timezone(settings.site_zone)
    create_daily_operation = CreateDailyOperation(
        repository,
        resolved_routing_provider,
        site_timezone=settings.site_zone,
        vehicle_catalog=resolved_vehicle_catalog,
    )
    get_daily_operation = GetDailyOperation(repository)
    prediction_history = SqlAlchemyPredictionHistoryRepository(session_factory)
    import_historical_dataset = ImportHistoricalDataset(
        SpreadsheetHistoricalDatasetSourceReader(),
        historical_dataset_repository,
        vehicle_catalog=resolved_vehicle_catalog,
    )
    get_dataset_valid_operations = GetDatasetValidOperations(historical_dataset_repository)
    if settings.mlflow_tracking_uri is not None:
        model_store = MlflowBaselineModelStore(
            settings.mlflow_tracking_uri, resolved_vehicle_catalog
        )
    else:
        if database_path is None:
            tracking_directory = settings.mlflow_tracking_directory
        else:
            tracking_directory = database_path.parent / "mlruns"
        model_store = MlflowBaselineModelStore.local(tracking_directory, resolved_vehicle_catalog)
    train_baseline_candidate = TrainBaselineCandidate(
        historical_dataset_repository, model_store, prediction_repository, resolved_vehicle_catalog
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
        resolved_vehicle_catalog,
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
    list_awaiting_actual = ListOperationsAwaitingActualFuel(actual_fuel_repository)
    promote_candidate_model = PromoteCandidateModel(prediction_repository, prediction_repository)
    get_candidate_model_comparison = GetCandidateModelComparison(
        prediction_repository, actual_fuel_repository, model_store, resolved_vehicle_catalog
    )
    get_model_governance_dashboard = GetModelGovernanceDashboard(
        prediction_repository,
        actual_fuel_repository,
        model_store,
        settings.max_active_model_mae_liters,
        resolved_vehicle_catalog,
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
        resolved_vehicle_catalog,
    )
    password_hasher = ScryptPasswordHasher()
    record_audit = RecordAuditEvent(audit_repository)
    sign_in = SignIn(user_repository, session_repository, password_hasher, record_audit)
    sign_out = SignOut(session_repository)
    resolve_session = ResolveSession(
        user_repository,
        session_repository,
        allow_unprovisioned_access=(
            settings.allow_unprovisioned_access
            if allow_unprovisioned_access is None
            else allow_unprovisioned_access
        ),
    )
    create_user = CreateUser(user_repository, password_hasher, record_audit)
    list_users = ListUsers(user_repository)
    set_user_activation = SetUserActivation(user_repository, session_repository, record_audit)
    change_password = ChangePassword(
        user_repository, session_repository, password_hasher, record_audit
    )
    change_own_password = ChangeOwnPassword(user_repository, password_hasher, change_password)
    user_activity = SqlAlchemyUserActivityRepository(session_factory)
    events = ImportantEvents(record_audit)
    reset_mailer = (
        password_reset_mailer
        if password_reset_mailer is not None
        else build_password_reset_mailer(settings)
    )
    request_password_reset = RequestPasswordReset(
        user_repository,
        SqlAlchemyPasswordResetTokenRepository(session_factory),
        reset_mailer,
        record_audit,
    )
    reset_password = ResetPasswordWithToken(
        user_repository, SqlAlchemyPasswordResetTokenRepository(session_factory), change_password
    )
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
        health_check=answers_a_representative_case(HEALTH_CHECK_FEATURES),
        record_rollback=_rollback_recorder(record_audit),
    )
    agent_client_repository = SqlAlchemyAgentClientRepository(session_factory)
    issue_agent_credential = IssueAgentCredential(agent_client_repository, record_audit)
    revoke_agent_credential = RevokeAgentCredential(agent_client_repository, record_audit)
    list_agent_clients = ListAgentClients(agent_client_repository)
    # OAuth grants (ADR 0014): a user connecting their own coding agent.
    agent_registrations = SqlAlchemyAgentRegistrationRepository(session_factory)
    authorization_codes = SqlAlchemyAuthorizationCodeRepository(session_factory)
    agent_grants = SqlAlchemyAgentGrantRepository(session_factory)
    list_agent_grants = ListAgentGrants(agent_grants, agent_registrations, user_repository)
    revoke_agent_grant = RevokeAgentGrant(agent_grants, record_audit)
    find_similar_operations = FindSimilarOperations(
        SqlAlchemyHistoricalOperationSource(session_factory), resolved_vehicle_catalog
    )
    mcp_registry = build_registry(
        generate_prediction=generate_fuel_prediction,
        create_operation=create_daily_operation,
        monitoring_dashboard=get_monitoring_dashboard,
        prediction_performance=get_prediction_performance,
        model_reader=prediction_repository,
        monitoring_runs=monitoring_run_repository,
        has_retained_package=activate_retained_package.can_activate,
        vehicle_catalog=resolved_vehicle_catalog,
        location_catalog=resolved_location_catalog,
        find_similar_operations=find_similar_operations,
        # The same provider the planner's page previews with, so an agent and
        # a human asking about the same stops get the same kilometres.
        route_preview=resolved_route_preview,
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
        # Either kind of bearer: an administrator-issued credential or a
        # token from a user's grant. The handler never learns which.
        resolve_credential=ResolveAgentBearer(
            resolve_credential=ResolveAgentCredential(agent_client_repository),
            resolve_grant=ResolveGrantAccessToken(
                agent_grants, agent_registrations, user_repository
            ),
        ),
        record_audit=record_audit,
        max_calls_per_window=settings.mcp_max_calls_per_window,
        window_seconds=settings.mcp_rate_limit_window_seconds,
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
        title="Fuel Matrix Calculation",
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
            request_password_reset=request_password_reset,
            reset_password=reset_password,
            reset_mail_configured=reset_mailer.is_configured,
            public_url=resolved_public_url,
        )
    )
    app.include_router(
        build_user_pages_router(
            create_user=create_user,
            get_user_directory=GetUserDirectory(user_repository, audit_repository, user_activity),
            get_user_detail=GetUserDetail(
                user_repository, audit_repository, user_activity, trail_limit=20
            ),
            update_user_profile=UpdateUserProfile(user_repository, record_audit),
            set_user_activation=set_user_activation,
            change_password=change_password,
            change_own_password=change_own_password,
            guard=guard,
        )
    )
    app.include_router(
        build_dashboard_router(
            get_monitoring_dashboard,
            get_model_governance_dashboard,
            list_audit_records,
            list_awaiting_actual,
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
            get_daily_operation,
            ListRecentPredictions(prediction_history),
            GetLatestPrediction(prediction_history),
            guard,
            resolved_location_catalog,
            resolved_vehicle_catalog,
            resolved_route_preview,
            find_similar_operations,
            events=events,
        )
    )
    app.include_router(
        build_bulk_prediction_pages_router(
            bulk_operation_prediction,
            guard,
            events=events,
        )
    )
    app.include_router(build_fleet_pages_router(resolved_vehicle_catalog, guard))
    app.include_router(
        build_actual_fuel_pages_router(
            record_actual_fuel,
            bulk_actual_fuel,
            list_awaiting_actual,
            guard,
            events=events,
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
            events=events,
        )
    )
    app.include_router(
        build_historical_dataset_pages_router(
            import_historical_dataset,
            train_baseline_candidate,
            guard,
            events=events,
        )
    )
    app.include_router(
        build_model_governance_pages_router(
            promote_candidate_model,
            activate_retained_package,
            get_candidate_model_comparison,
            get_model_governance_dashboard,
            guard,
            events=events,
        )
    )
    app.include_router(
        build_model_upload_pages_router(
            validate_package,
            validation_records,
            artifact_store,
            register_ingested_package,
            guard,
            events=events,
        )
    )
    app.include_router(
        build_mcp_router(mcp_handler, server_version="1.0.0", public_url=resolved_public_url)
    )
    app.include_router(
        build_agent_pages_router(
            issue_agent_credential,
            revoke_agent_credential,
            list_agent_clients,
            guard,
            rate_limit_per_minute=settings.mcp_max_calls_per_window
            * 60
            // settings.mcp_rate_limit_window_seconds,
            list_grants=list_agent_grants,
            revoke_grant=revoke_agent_grant,
            rename_grant=RenameAgentGrant(agent_grants, record_audit),
            delete_grant=DeleteAgentGrant(agent_grants, record_audit),
        )
    )
    app.include_router(
        build_oauth_router(
            register_client=RegisterAgentClient(agent_registrations, record_audit),
            validate_request=ValidateAuthorizationRequest(agent_registrations),
            issue_code=IssueAuthorizationCode(authorization_codes, record_audit),
            redeem_code=RedeemAuthorizationCode(
                authorization_codes, agent_grants, user_repository, record_audit
            ),
            refresh_grant=RefreshGrant(agent_grants, user_repository, record_audit),
            revoke_by_token=RevokeGrantByToken(agent_grants, record_audit),
            guard=guard,
            is_system_provisioned=resolve_session.is_system_provisioned,
            public_url=resolved_public_url,
        )
    )
    app.include_router(
        build_health_router(
            session_factory,
            monitoring_run_repository,
            settings.monitoring_stale_after_hours,
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
            # Same source of truth the monitoring job uses, so the page cannot
            # claim alerts are delivered when the job would say otherwise.
            alert_channel_configured=build_notifier(settings).is_configured,
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


app = create_app()
