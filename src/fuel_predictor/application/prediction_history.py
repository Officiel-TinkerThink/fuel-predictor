"""Looking predictions up again after the page that showed them is gone."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fuel_predictor.domain.daily_operation import VehicleCategory
from fuel_predictor.domain.prediction import FuelPrediction


@dataclass(frozen=True, slots=True)
class PredictionHistoryEntry:
    """One operation's latest estimate, with what a person needs to recognise
    the day and whether its real consumption has been reported since."""

    operation_id: str
    predicted_at: datetime
    vehicle: str | None
    vehicle_category: VehicleCategory
    departure: str | None
    destination: str | None
    stop_count: int
    total_distance_km: float
    estimated_fuel_requirement_liters: float
    recommended_allocation_liters: float
    actual_fuel_liters: float | None
    operation_code: str | None = None
    # Which model made the estimate, so a planner can tell one model's
    # numbers from the next's.
    model_version_id: str | None = None
    model_code: str | None = None
    # Withdrawn before any actual fuel: nothing more to record for it.
    cancelled: bool = False


class PredictionHistoryReader(Protocol):
    def get_recent_predictions(self, limit: int) -> Sequence[PredictionHistoryEntry]: ...

    def get_latest_prediction(self, operation_id: str) -> FuelPrediction | None: ...


@dataclass(frozen=True, slots=True)
class ListRecentPredictions:
    reader: PredictionHistoryReader
    limit: int = 50

    def execute(self, limit: int | None = None) -> tuple[PredictionHistoryEntry, ...]:
        return tuple(self.reader.get_recent_predictions(limit or self.limit))


@dataclass(frozen=True, slots=True)
class GetLatestPrediction:
    """An operation may be predicted more than once; the newest is the one
    that counts, and the one the history page links to."""

    reader: PredictionHistoryReader

    def execute(self, operation_id: str) -> FuelPrediction | None:
        return self.reader.get_latest_prediction(operation_id)
