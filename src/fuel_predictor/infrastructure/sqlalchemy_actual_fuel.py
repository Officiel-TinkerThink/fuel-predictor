from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    ModelEvaluationCase,
    PredictionOutcome,
)
from fuel_predictor.domain.actual_fuel import (
    ActualFuelRecord,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.infrastructure.database import (
    ActualFuelRecordRow,
    DailyOperationRow,
    PredictionRow,
    SessionFactory,
)


class SqlAlchemyActualFuelRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, record: ActualFuelRecord) -> None:
        try:
            with self._session_factory.begin() as session:
                session.add(
                    ActualFuelRecordRow(
                        operation_id=record.operation_id,
                        actual_fuel_liters=record.actual_fuel_liters,
                        measurement_source=record.measurement_source.value,
                        status=record.status.value,
                        recorded_at=record.recorded_at,
                        source_filename=record.source_filename,
                        source_sheet_name=record.source_sheet_name,
                        source_row_number=record.source_row_number,
                    )
                )
        except IntegrityError as error:
            raise ActualFuelAlreadyRecordedError() from error

    def get_prediction_outcomes(self) -> tuple[PredictionOutcome, ...]:
        latest_prediction_id = (
            select(PredictionRow.prediction_id)
            .where(PredictionRow.operation_id == ActualFuelRecordRow.operation_id)
            .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
            .limit(1)
            .correlate(ActualFuelRecordRow)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DailyOperationRow.vehicle_category,
                    PredictionRow.estimated_fuel_requirement_liters,
                    PredictionRow.uncertainty_lower_liters,
                    PredictionRow.uncertainty_upper_liters,
                    ActualFuelRecordRow.actual_fuel_liters,
                )
                .select_from(ActualFuelRecordRow)
                .join(
                    DailyOperationRow,
                    DailyOperationRow.operation_id == ActualFuelRecordRow.operation_id,
                )
                .join(PredictionRow, PredictionRow.prediction_id == latest_prediction_id)
            ).all()
        return tuple(
            PredictionOutcome(
                vehicle_category=VehicleCategory(row.vehicle_category),
                estimated_fuel_requirement_liters=row.estimated_fuel_requirement_liters,
                uncertainty_lower_liters=row.uncertainty_lower_liters,
                uncertainty_upper_liters=row.uncertainty_upper_liters,
                actual_fuel_liters=row.actual_fuel_liters,
            )
            for row in rows
        )

    def get_model_evaluation_cases(self) -> tuple[ModelEvaluationCase, ...]:
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DailyOperationRow.operation_id,
                    DailyOperationRow.vehicle_category,
                    DailyOperationRow.activity_mode,
                    DailyOperationRow.lifting_hours,
                    DailyOperationRow.total_distance_km,
                    DailyOperationRow.distance_source,
                    DailyOperationRow.route_distance_manual_fallback,
                    ActualFuelRecordRow.actual_fuel_liters,
                )
                .select_from(ActualFuelRecordRow)
                .join(
                    DailyOperationRow,
                    DailyOperationRow.operation_id == ActualFuelRecordRow.operation_id,
                )
            ).all()
        return tuple(
            ModelEvaluationCase(
                operation=DailyOperation(
                    operation_id=row.operation_id,
                    vehicle_category=VehicleCategory(row.vehicle_category),
                    activity_mode=ActivityMode(row.activity_mode),
                    lifting_hours=row.lifting_hours,
                    total_distance_km=row.total_distance_km,
                    distance_source=DistanceSource(row.distance_source),
                    route_distance_manual_fallback=row.route_distance_manual_fallback,
                ),
                actual_fuel_liters=row.actual_fuel_liters,
            )
            for row in rows
        )
