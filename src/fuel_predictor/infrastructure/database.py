from datetime import datetime

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
    )

    operation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    vehicle_category: Mapped[str] = mapped_column(String(64), nullable=False)
    activity_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    lifting_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    distance_source: Mapped[str] = mapped_column(String(64), nullable=False)
    route_distance_manual_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)


class DailyOperationStopRow(Base):
    __tablename__ = "daily_operation_stops"

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id", ondelete="CASCADE"), primary_key=True
    )
    stop_position: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_name: Mapped[str] = mapped_column(String(512), nullable=False)


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
    model_version_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id"), nullable=False, index=True
    )
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertainty_liters: Mapped[float] = mapped_column(Float, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PredictionRow(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("daily_operations.operation_id"), nullable=False, index=True
    )
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.model_version_id"), nullable=False, index=True
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


type SessionFactory = sessionmaker[Session]


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema_for_tests(engine: Engine) -> None:
    Base.metadata.create_all(engine)
