from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fuel_predictor.domain.daily_operation import DistanceSource


class ModelLifecycleStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_version_id: str
    version: int
    dataset_version_id: str
    feature_version: str
    algorithm: str
    artifact_uri: str
    trained_at: datetime
    training_row_count: int
    uncertainty_liters: float
    lifecycle_status: ModelLifecycleStatus = ModelLifecycleStatus.CANDIDATE
    promoted_at: datetime | None = None
    retired_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FuelPrediction:
    prediction_id: str
    operation_id: str
    model: ModelVersion
    estimated_fuel_requirement_liters: float
    recommended_allocation_liters: float
    uncertainty_lower_liters: float
    uncertainty_upper_liters: float
    route_distance_source: DistanceSource
    safety_policy: str
    route_distance_manual_fallback: bool
    input_snapshot: dict[str, str | float | bool | list[str] | None]
    feature_values: dict[str, str | float]
    created_at: datetime
