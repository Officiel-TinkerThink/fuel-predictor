from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fuel_predictor.domain.daily_operation import VehicleCategory


class MonitoringAlertKind(StrEnum):
    DATA_QUALITY = "data_quality"
    MISSING_ACTUAL = "missing_actual"
    FEATURE_DRIFT = "feature_drift"
    MODEL_DEGRADATION = "model_degradation"


class MonitoringAlertSeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class MonitoringAlert:
    alert_key: str
    kind: MonitoringAlertKind
    severity: MonitoringAlertSeverity
    message: str
    details: dict[str, str | int | float | bool | list[str]]
    first_observed_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DatasetValidationSummary:
    dataset_version_id: str
    version: int
    source_filename: str
    imported_at: datetime
    valid_operation_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int


@dataclass(frozen=True, slots=True)
class UnresolvedDataQualityIssue:
    dataset_version_id: str
    source_filename: str
    sheet_name: str
    row_number: int
    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MissingActualPrediction:
    prediction_id: str
    operation_id: str
    created_at: datetime
    vehicle_category: VehicleCategory


@dataclass(frozen=True, slots=True)
class FeatureDriftSummary:
    reference_row_count: int
    current_row_count: int
    status: str
    drift_share: float | None
    threshold: float
    drifting_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TimedPredictionOutcome:
    vehicle_category: VehicleCategory
    estimated_fuel_requirement_liters: float
    actual_fuel_liters: float
    prediction_created_at: datetime
    actual_recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RollingErrorPoint:
    observed_at: datetime
    matched_record_count: int
    mae_liters: float


@dataclass(frozen=True, slots=True)
class CategoryDegradation:
    vehicle_category: VehicleCategory
    matched_record_count: int
    rolling_mae_liters: float | None
    threshold_liters: float
    degraded: bool
