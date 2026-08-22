from datetime import datetime

from sqlalchemy import select, update

from fuel_predictor.application.baseline_predictions import (
    ActiveModelVersionReader,
    ModelVersionWriter,
    PredictionWriter,
)
from fuel_predictor.domain.prediction import (
    FuelPrediction,
    ModelLifecycleStatus,
    ModelVersion,
)
from fuel_predictor.infrastructure.database import ModelVersionRow, PredictionRow, SessionFactory


class SqlAlchemyPredictionRepository(
    ModelVersionWriter, ActiveModelVersionReader, PredictionWriter
):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, model: ModelVersion) -> ModelVersion:
        return self._add_model(model)

    def add(self, prediction: FuelPrediction) -> None:
        self._add_prediction(prediction)

    def get_active(self) -> ModelVersion | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(ModelVersionRow).where(
                    ModelVersionRow.lifecycle_status == ModelLifecycleStatus.ACTIVE.value
                )
            )
            return _to_model(row) if row is not None else None

    def get(self, model_version_id: str) -> ModelVersion | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(ModelVersionRow).where(ModelVersionRow.model_version_id == model_version_id)
            )
            return _to_model(row) if row is not None else None

    def list_candidates(self) -> tuple[ModelVersion, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ModelVersionRow)
                .where(ModelVersionRow.lifecycle_status == ModelLifecycleStatus.CANDIDATE.value)
                .order_by(ModelVersionRow.version.desc())
            )
            return tuple(_to_model(row) for row in rows)

    def promote(self, model_version_id: str, promoted_at: datetime) -> ModelVersion | None:
        with self._session_factory.begin() as session:
            row = session.scalar(
                select(ModelVersionRow).where(ModelVersionRow.model_version_id == model_version_id)
            )
            if row is None:
                return None
            if row.lifecycle_status == ModelLifecycleStatus.ACTIVE.value:
                return _to_model(row)
            if row.lifecycle_status != ModelLifecycleStatus.CANDIDATE.value:
                raise ValueError("retired_model_cannot_be_promoted")
            session.execute(
                update(ModelVersionRow)
                .where(ModelVersionRow.lifecycle_status == ModelLifecycleStatus.ACTIVE.value)
                .values(
                    lifecycle_status=ModelLifecycleStatus.RETIRED.value,
                    retired_at=promoted_at,
                )
            )
            row.lifecycle_status = ModelLifecycleStatus.ACTIVE.value
            row.promoted_at = promoted_at
            session.flush()
            return _to_model(row)

    def _add_model(self, model: ModelVersion) -> ModelVersion:
        with self._session_factory.begin() as session:
            row = ModelVersionRow(
                model_version_id=model.model_version_id,
                dataset_version_id=model.dataset_version_id,
                feature_version=model.feature_version,
                algorithm=model.algorithm,
                artifact_uri=model.artifact_uri,
                trained_at=model.trained_at,
                training_row_count=model.training_row_count,
                uncertainty_liters=model.uncertainty_liters,
                lifecycle_status=model.lifecycle_status.value,
                promoted_at=model.promoted_at,
                retired_at=model.retired_at,
            )
            session.add(row)
            session.flush()
            return _to_model(row)

    def _add_prediction(self, prediction: FuelPrediction) -> None:
        with self._session_factory.begin() as session:
            session.add(
                PredictionRow(
                    prediction_id=prediction.prediction_id,
                    operation_id=prediction.operation_id,
                    model_version_id=prediction.model.model_version_id,
                    dataset_version_id=prediction.model.dataset_version_id,
                    feature_version=prediction.model.feature_version,
                    estimated_fuel_requirement_liters=prediction.estimated_fuel_requirement_liters,
                    recommended_allocation_liters=prediction.recommended_allocation_liters,
                    uncertainty_lower_liters=prediction.uncertainty_lower_liters,
                    uncertainty_upper_liters=prediction.uncertainty_upper_liters,
                    route_distance_source=prediction.route_distance_source.value,
                    route_distance_manual_fallback=prediction.route_distance_manual_fallback,
                    safety_policy=prediction.safety_policy,
                    input_snapshot=prediction.input_snapshot,
                    feature_values=prediction.feature_values,
                    created_at=prediction.created_at,
                )
            )


def _to_model(row: ModelVersionRow) -> ModelVersion:
    return ModelVersion(
        model_version_id=row.model_version_id,
        version=row.version,
        dataset_version_id=row.dataset_version_id,
        feature_version=row.feature_version,
        algorithm=row.algorithm,
        artifact_uri=row.artifact_uri,
        trained_at=row.trained_at,
        training_row_count=row.training_row_count,
        uncertainty_liters=row.uncertainty_liters,
        lifecycle_status=ModelLifecycleStatus(row.lifecycle_status),
        promoted_at=row.promoted_at,
        retired_at=row.retired_at,
    )
