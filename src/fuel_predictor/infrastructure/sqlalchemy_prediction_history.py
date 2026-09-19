from typing import cast

from sqlalchemy import select

from fuel_predictor.application.prediction_history import PredictionHistoryEntry
from fuel_predictor.domain.daily_operation import DistanceSource, VehicleCategory
from fuel_predictor.domain.prediction import FuelPrediction
from fuel_predictor.infrastructure.database import (
    ActualFuelRecordRow,
    DailyOperationRow,
    ModelVersionRow,
    PredictionRow,
    SessionFactory,
)
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import stops_for
from fuel_predictor.infrastructure.sqlalchemy_predictions import _to_model


class SqlAlchemyPredictionHistoryRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_recent_predictions(self, limit: int) -> tuple[PredictionHistoryEntry, ...]:
        latest_prediction_id = (
            select(PredictionRow.prediction_id)
            .where(PredictionRow.operation_id == DailyOperationRow.operation_id)
            .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
            .limit(1)
            .correlate(DailyOperationRow)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DailyOperationRow.operation_id,
                    DailyOperationRow.vehicle,
                    DailyOperationRow.vehicle_category,
                    DailyOperationRow.total_distance_km,
                    PredictionRow.created_at,
                    PredictionRow.estimated_fuel_requirement_liters,
                    PredictionRow.recommended_allocation_liters,
                    ActualFuelRecordRow.actual_fuel_liters,
                )
                .select_from(DailyOperationRow)
                .join(PredictionRow, PredictionRow.prediction_id == latest_prediction_id)
                .outerjoin(
                    ActualFuelRecordRow,
                    ActualFuelRecordRow.operation_id == DailyOperationRow.operation_id,
                )
                .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
                .limit(limit)
            ).all()
            stops = stops_for(session, [row.operation_id for row in rows])
        return tuple(
            PredictionHistoryEntry(
                operation_id=row.operation_id,
                predicted_at=row.created_at,
                vehicle=row.vehicle,
                vehicle_category=VehicleCategory(row.vehicle_category),
                departure=stops[row.operation_id][0] if stops[row.operation_id] else None,
                destination=stops[row.operation_id][-1] if stops[row.operation_id] else None,
                stop_count=len(stops[row.operation_id]),
                total_distance_km=row.total_distance_km,
                estimated_fuel_requirement_liters=row.estimated_fuel_requirement_liters,
                recommended_allocation_liters=row.recommended_allocation_liters,
                actual_fuel_liters=row.actual_fuel_liters,
            )
            for row in rows
        )

    def get_latest_prediction(self, operation_id: str) -> FuelPrediction | None:
        with self._session_factory() as session:
            row = session.execute(
                select(PredictionRow, ModelVersionRow)
                .join(
                    ModelVersionRow,
                    ModelVersionRow.model_version_id == PredictionRow.model_version_id,
                )
                .where(PredictionRow.operation_id == operation_id)
                .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            prediction, model = row
            return FuelPrediction(
                prediction_id=prediction.prediction_id,
                operation_id=prediction.operation_id,
                model=_to_model(model),
                estimated_fuel_requirement_liters=prediction.estimated_fuel_requirement_liters,
                recommended_allocation_liters=prediction.recommended_allocation_liters,
                uncertainty_lower_liters=prediction.uncertainty_lower_liters,
                uncertainty_upper_liters=prediction.uncertainty_upper_liters,
                route_distance_source=DistanceSource(prediction.route_distance_source),
                safety_policy=prediction.safety_policy,
                route_distance_manual_fallback=prediction.route_distance_manual_fallback,
                input_snapshot=cast(
                    dict[str, str | float | bool | list[str] | None],
                    dict(prediction.input_snapshot),
                ),
                feature_values=cast(dict[str, str | float], dict(prediction.feature_values)),
                created_at=prediction.created_at,
            )
