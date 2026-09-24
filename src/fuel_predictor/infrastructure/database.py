from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class DailyOperationRow(Base):
    __tablename__ = "daily_operations"
    __table_args__ = (
        CheckConstraint("total_distance_km > 0", name="daily_operation_distance_gt_zero"),
        # A unique index rather than a constraint: both databases let any
        # number of rows leave it null (imported history has no code).
        Index("uq_daily_operations_operation_code", "operation_code", unique=True),
    )

    operation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # The operator-facing handle (ADR 0016), e.g. 260924-0914-VT-P410-VT01.
    operation_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_category: Mapped[str] = mapped_column(String(64), nullable=False)
    # The individual unit. Null for operations recorded before the fleet was
    # identified, which is why the column is nullable rather than defaulted.
    vehicle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    lifting_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    distance_source: Mapped[str] = mapped_column(String(64), nullable=False)
    route_distance_manual_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Who planned it and when; null on rows from before this was recorded.
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailyOperationStopRow(Base):
    __tablename__ = "daily_operation_stops"

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id", ondelete="CASCADE"), primary_key=True
    )
    stop_position: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_name: Mapped[str] = mapped_column(String(512), nullable=False)
    # What the vehicle does at this stop. Null for the departure point, and for
    # operations recorded before stops carried an activity of their own.
    activity: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DailyOperationSourceRow(Base):
    __tablename__ = "daily_operation_sources"

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id", ondelete="CASCADE"), primary_key=True
    )
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    raw_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class DatasetVersionRow(Base):
    __tablename__ = "dataset_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_operation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantined_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ignored_blank_row_count: Mapped[int] = mapped_column(Integer, nullable=False)


class HistoricalDailyOperationRow(Base):
    __tablename__ = "historical_daily_operations"
    __table_args__ = (CheckConstraint("total_distance_km > 0", name="historical_distance_gt_zero"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id: Mapped[str] = mapped_column(String(40), nullable=False)
    vehicle_category: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    lifting_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    distance_source: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_fuel_liters: Mapped[float] = mapped_column(Float, nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    raw_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)


class DataQualityIssueRow(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    reasons: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    raw_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ModelVersionRow(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        Index(
            "ux_model_versions_one_active",
            "lifecycle_status",
            unique=True,
            sqlite_where=text("lifecycle_status = 'active'"),
            postgresql_where=text("lifecycle_status = 'active'"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 64, as the package manifest allows; 40 once rejected longer package names.
    model_version_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # M-260924-01: the name people use. Always set by the repository; nullable
    # only because SQLite cannot add a NOT NULL column to a populated table.
    model_code: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True)
    # Provenance, not a local reference. A model trained here names a dataset
    # this application imported; an ingested package names one from the
    # builder's environment that need not exist here. A foreign key asserted
    # the second case was the first and made package upload fail on PostgreSQL.
    dataset_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertainty_liters: Mapped[float] = mapped_column(Float, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    catalog_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PredictionRow(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id"), nullable=False, index=True
    )
    model_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_versions.model_version_id"), nullable=False, index=True
    )
    dataset_version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_fuel_requirement_liters: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_allocation_liters: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty_lower_liters: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty_upper_liters: Mapped[float] = mapped_column(Float, nullable=False)
    route_distance_source: Mapped[str] = mapped_column(String(64), nullable=False)
    route_distance_manual_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)
    safety_policy: Mapped[str] = mapped_column(String(1024), nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    feature_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActualFuelRecordRow(Base):
    __tablename__ = "actual_fuel_records"
    __table_args__ = (CheckConstraint("actual_fuel_liters > 0", name="actual_fuel_liters_gt_zero"),)

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id", ondelete="RESTRICT"), primary_key=True
    )
    actual_fuel_liters: Mapped[float] = mapped_column(Float, nullable=False)
    measurement_source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Normalised before it gets here, so a plain unique index is enough.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordResetTokenRow(Base):
    """A mailed reset link, by hash. Single use; expired rows are swept on the next request."""

    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSessionRow(Base):
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)


class AuditRecordRow(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_action_subject", "action", "subject", "occurred_at"),
        # The MCP rate limiter counts one actor's recent records on every tool
        # call, and audit_records grows without bound. Without this the query
        # scans the whole window, and does so most often when an agent is
        # looping — exactly when it must stay cheap.
        Index("ix_audit_records_actor_occurred_at", "actor", "occurred_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ModelPackageValidationRow(Base):
    """One recorded verdict on an uploaded package (plan validation step 9).

    Kept even when the verdict is a rejection: an operator asking "why was
    this package refused?" needs the answer to still exist, and a rejected
    upload is exactly the thing someone reconstructs later.
    """

    __tablename__ = "model_package_validations"

    validation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    manifest: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class AgentClientRow(Base):
    """An MCP client credential (ADR 0008, Phase 4).

    Only the token hash is stored. A lost credential is reissued, never
    recovered, so a database read cannot yield a working token.
    """

    __tablename__ = "agent_clients"

    client_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRegistrationRow(Base):
    """A program that registered itself as an OAuth client (ADR 0014).

    Public clients only, so there is no secret column to protect. The name is
    the client's own claim and is shown to the user as such.
    """

    __tablename__ = "agent_registrations"

    registration_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorizationCodeRow(Base):
    """A user's consent on its way to the client: single use, minutes to live."""

    __tablename__ = "agent_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    registration_id: Mapped[str] = mapped_column(
        ForeignKey("agent_registrations.registration_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentGrantRow(Base):
    """A user's standing delegation to one registered client (ADR 0014).

    Both token hashes live on the grant and are replaced together on refresh,
    so one row is one consent and revoking it ends every token it ever had.
    """

    __tablename__ = "agent_grants"

    grant_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    registration_id: Mapped[str] = mapped_column(
        ForeignKey("agent_registrations.registration_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    access_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    refresh_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MonitoringRunRow(Base):
    """One completed scheduled monitoring run (Phase 3).

    Stored so the UI and MCP read a precomputed summary instead of
    recomputing drift and reconciliation inside a page request, and so
    "when did monitoring last succeed?" has an answer even when the most
    recent attempt failed.
    """

    __tablename__ = "monitoring_runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class BackupRunRow(Base):
    """Outcome of the most recent backup attempt (Phase 3 / ADR 0012).

    Recorded by the backup job rather than inferred: the application cannot
    see whether an off-VM upload succeeded, and guessing would produce a
    reassuring dashboard with no basis.
    """

    __tablename__ = "backup_runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    destination: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class MonitoringAlertRow(Base):
    __tablename__ = "monitoring_alerts"

    alert_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LocationRow(Base):
    """The planner's stop points, imported from the "Data Lokasi" sheet.

    The name is the key because that is what the sheet keys on: its per-vehicle
    trip logs resolve coordinates by looking a typed stop name up against this
    list, and `daily_operation_stops` records the same name.
    """

    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="location_latitude_in_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="location_longitude_in_range"),
    )

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # The raw reading the coordinates were derived from, kept so a surveyed
    # value stays traceable to what the sheet recorded.
    satellite_point: Mapped[str | None] = mapped_column(String(255), nullable=True)


class VehicleRow(Base):
    """The fleet, imported from the planner's "Dim_Kendaraan" sheet.

    Keyed by name because that is the key the source sheet uses and the name is
    what a daily operation records. `aliases` holds the other spellings the same
    vehicle appears under, so importing history resolves them to one vehicle
    instead of scattering it across several.
    """

    __tablename__ = "vehicles"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    vehicle_group: Mapped[str] = mapped_column(String(64), nullable=False)
    # The finer cut inside a group (ADR 0015); equals the group until the
    # owner splits one.
    vehicle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # The short codes that make up a vehicle code, VT-P410-VT01 (ADR 0016).
    # Empty when the sheet gives none: a type that is only its group has no code.
    group_code: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    type_code: Mapped[str] = mapped_column(String(8), nullable=False, default="")


type SessionFactory = sessionmaker[Session]


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        # SQLite ignores foreign keys unless each connection opts in, while
        # PostgreSQL always enforces them. Leaving the default meant the suite
        # accepted dangling references that made real requests fail with a 500
        # in production. Tests should fail where production fails.
        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(connection: Any, _record: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema_for_tests(engine: Engine) -> None:
    Base.metadata.create_all(engine)


class AlertNotificationRow(Base):
    """Which alerts an operator has already been told about (Phase 3).

    Persisted because the monitoring job is a separate short-lived process: an
    in-memory record of "already sent" would be empty on every run, and the
    operator would receive the same warning on every tick until they stopped
    reading them.
    """

    __tablename__ = "alert_notifications"

    alert_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
