from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from typing import Protocol

from fuel_predictor.application.daily_operations import (
    DailyOperationNotFoundError,
    DailyOperationReader,
)
from fuel_predictor.domain.actual_fuel import (
    ActualFuelMeasurementSource,
    ActualFuelRecord,
    ActualFuelStatus,
)
from fuel_predictor.domain.daily_operation import DailyOperation, VehicleCategory


class ActualFuelWriter(Protocol):
    def add(self, record: ActualFuelRecord) -> None: ...


class PredictionOutcomeReader(Protocol):
    def get_prediction_outcomes(self) -> Sequence["PredictionOutcome"]: ...


class ActualFuelAlreadyRecordedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecordActualFuelCommand:
    operation_id: str
    actual_fuel_liters: float
    measurement_source: ActualFuelMeasurementSource
    source_filename: str | None = None
    source_sheet_name: str | None = None
    source_row_number: int | None = None


@dataclass(frozen=True, slots=True)
class RecordActualFuel:
    operation_reader: DailyOperationReader
    actual_fuel_writer: ActualFuelWriter
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, command: RecordActualFuelCommand) -> ActualFuelRecord:
        if self.operation_reader.get(command.operation_id) is None:
            raise DailyOperationNotFoundError(command.operation_id)
        if command.actual_fuel_liters <= 0:
            raise ValueError("Bahan bakar aktual harus lebih besar dari 0.")
        record = ActualFuelRecord(
            operation_id=command.operation_id,
            actual_fuel_liters=command.actual_fuel_liters,
            measurement_source=command.measurement_source,
            status=ActualFuelStatus.RECORDED,
            recorded_at=self.now(),
            source_filename=command.source_filename,
            source_sheet_name=command.source_sheet_name,
            source_row_number=command.source_row_number,
        )
        self.actual_fuel_writer.add(record)
        return record


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    vehicle_category: VehicleCategory
    estimated_fuel_requirement_liters: float
    uncertainty_lower_liters: float
    uncertainty_upper_liters: float
    actual_fuel_liters: float


@dataclass(frozen=True, slots=True)
class ModelEvaluationCase:
    operation: DailyOperation
    actual_fuel_liters: float


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    matched_record_count: int
    mae_liters: float | None
    rmse_liters: float | None
    smape_percent: float | None
    interval_coverage_percent: float | None


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    overall: PerformanceMetrics
    by_vehicle_category: tuple[tuple[VehicleCategory, PerformanceMetrics], ...]


@dataclass(frozen=True, slots=True)
class GetPredictionPerformance:
    outcome_reader: PredictionOutcomeReader

    def execute(self) -> PerformanceReport:
        outcomes = tuple(self.outcome_reader.get_prediction_outcomes())
        categories = tuple(sorted({outcome.vehicle_category for outcome in outcomes}, key=str))
        return PerformanceReport(
            overall=calculate_performance_metrics(outcomes),
            by_vehicle_category=tuple(
                (
                    category,
                    calculate_performance_metrics(
                        tuple(
                            outcome for outcome in outcomes if outcome.vehicle_category == category
                        )
                    ),
                )
                for category in categories
            ),
        )


def calculate_performance_metrics(outcomes: Sequence[PredictionOutcome]) -> PerformanceMetrics:
    if not outcomes:
        return PerformanceMetrics(0, None, None, None, None)

    errors = [
        outcome.estimated_fuel_requirement_liters - outcome.actual_fuel_liters
        for outcome in outcomes
    ]
    smape_values = [
        200
        * abs(error)
        / (abs(outcome.estimated_fuel_requirement_liters) + abs(outcome.actual_fuel_liters))
        for outcome, error in zip(outcomes, errors, strict=True)
    ]
    covered = sum(
        outcome.uncertainty_lower_liters
        <= outcome.actual_fuel_liters
        <= outcome.uncertainty_upper_liters
        for outcome in outcomes
    )
    count = len(outcomes)
    return PerformanceMetrics(
        matched_record_count=count,
        mae_liters=sum(abs(error) for error in errors) / count,
        rmse_liters=sqrt(sum(error**2 for error in errors) / count),
        smape_percent=sum(smape_values) / count,
        interval_coverage_percent=(covered / count) * 100,
    )
