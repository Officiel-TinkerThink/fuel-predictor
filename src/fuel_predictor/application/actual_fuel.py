from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from typing import Protocol

from fuel_predictor.application.daily_operations import (
    DailyOperationLookup,
    find_daily_operation,
)
from fuel_predictor.domain.actual_fuel import (
    ActualFuelMeasurementSource,
    ActualFuelRecord,
    ActualFuelStatus,
)
from fuel_predictor.domain.daily_operation import DailyOperation, VehicleCategory
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


class ActualFuelWriter(Protocol):
    def add(self, record: ActualFuelRecord) -> None: ...


class PredictionOutcomeReader(Protocol):
    def get_prediction_outcomes(self) -> Sequence["PredictionOutcome"]: ...


class PerformanceModelReader(Protocol):
    """The models a performance report names: each one's code, status and the
    error it declared at training."""

    def get(self, model_version_id: str) -> ModelVersion | None: ...

    def get_active(self) -> ModelVersion | None: ...


class AwaitingActualFuelReader(Protocol):
    def get_operations_awaiting_actual(
        self, limit: int | None
    ) -> Sequence["OperationAwaitingActualFuel"]: ...


class ActualFuelAlreadyRecordedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecordActualFuelCommand:
    # The operation code the operator wrote down, or the `OPR-…` id.
    operation_reference: str
    actual_fuel_liters: float
    measurement_source: ActualFuelMeasurementSource
    source_filename: str | None = None
    source_sheet_name: str | None = None
    source_row_number: int | None = None
    recorded_by: str | None = None


@dataclass(frozen=True, slots=True)
class RecordActualFuel:
    operation_reader: DailyOperationLookup
    actual_fuel_writer: ActualFuelWriter
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, command: RecordActualFuelCommand) -> ActualFuelRecord:
        operation = find_daily_operation(self.operation_reader, command.operation_reference)
        if command.actual_fuel_liters <= 0:
            raise ValueError("Bahan bakar aktual harus lebih besar dari 0.")
        record = ActualFuelRecord(
            operation_id=operation.operation_id,
            actual_fuel_liters=command.actual_fuel_liters,
            measurement_source=command.measurement_source,
            status=ActualFuelStatus.RECORDED,
            recorded_at=self.now(),
            source_filename=command.source_filename,
            source_sheet_name=command.source_sheet_name,
            source_row_number=command.source_row_number,
            recorded_by=command.recorded_by,
        )
        self.actual_fuel_writer.add(record)
        return record


@dataclass(frozen=True, slots=True)
class OperationAwaitingActualFuel:
    """A predicted operation nobody has reported the real consumption for yet.

    Carries what a person needs to recognise the day - when, which unit, from
    where to where, how much was estimated - so the id never has to be typed.
    """

    operation_id: str
    predicted_at: datetime
    vehicle: str | None
    vehicle_category: VehicleCategory
    departure: str | None
    destination: str | None
    stop_count: int
    estimated_fuel_requirement_liters: float
    recommended_allocation_liters: float
    operation_code: str | None = None


@dataclass(frozen=True, slots=True)
class ListOperationsAwaitingActualFuel:
    """Newest first: the operation someone just finished is the one they came to record."""

    reader: AwaitingActualFuelReader
    limit: int | None = None

    def execute(self) -> tuple[OperationAwaitingActualFuel, ...]:
        return tuple(self.reader.get_operations_awaiting_actual(self.limit))


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    vehicle_category: VehicleCategory
    estimated_fuel_requirement_liters: float
    uncertainty_lower_liters: float
    uncertainty_upper_liters: float
    actual_fuel_liters: float
    # The model whose prediction this actual is compared with. None where an
    # outcome is scored outside the served history (a candidate evaluation).
    model_version_id: str | None = None


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
    # Mean of estimate - actual: negative means the estimates run short. A
    # model can have a fine MAE and still under-allocate every day.
    bias_liters: float | None = None


@dataclass(frozen=True, slots=True)
class ModelPerformance:
    """One model's field record: its own predictions against recorded actuals."""

    model: ModelVersion
    metrics: PerformanceMetrics


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    overall: PerformanceMetrics
    by_vehicle_category: tuple[tuple[VehicleCategory, PerformanceMetrics], ...]
    # The active model first, then the others newest first.
    by_model: tuple[ModelPerformance, ...] = ()


@dataclass(frozen=True, slots=True)
class GetPredictionPerformance:
    outcome_reader: PredictionOutcomeReader
    model_reader: PerformanceModelReader | None = None

    def execute(self) -> PerformanceReport:
        outcomes = tuple(self.outcome_reader.get_prediction_outcomes())
        categories = tuple(sorted({outcome.vehicle_category for outcome in outcomes}, key=str))
        return PerformanceReport(
            by_model=self._by_model(outcomes),
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

    def _by_model(self, outcomes: tuple[PredictionOutcome, ...]) -> tuple[ModelPerformance, ...]:
        """Each actual counts for the model that made the prediction it is
        compared with. The active model is listed even before its first
        matched actual, so a fresh promotion is visibly "not yet measured"."""
        if self.model_reader is None:
            return ()
        models: dict[str, ModelVersion] = {}
        active = self.model_reader.get_active()
        if active is not None:
            models[active.model_version_id] = active
        for model_version_id in {o.model_version_id for o in outcomes if o.model_version_id}:
            if model_version_id not in models:
                model = self.model_reader.get(model_version_id)
                if model is not None:
                    models[model_version_id] = model
        ordered = sorted(
            models.values(),
            key=lambda model: (
                model.lifecycle_status is not ModelLifecycleStatus.ACTIVE,
                -model.version,
            ),
        )
        return tuple(
            ModelPerformance(
                model=model,
                metrics=calculate_performance_metrics(
                    tuple(o for o in outcomes if o.model_version_id == model.model_version_id)
                ),
            )
            for model in ordered
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
        bias_liters=sum(errors) / count,
    )
