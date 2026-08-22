from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fuel_predictor.application.baseline_predictions import (
    ActiveModelVersionReader,
    ModelVersionWriter,
    PredictionWriter,
)
from fuel_predictor.application.model_activation import ActivationTransition
from fuel_predictor.domain.model_activation import (
    ModelNotActivatableError,
    ModelVersionNotFoundError,
)
from fuel_predictor.domain.prediction import (
    FuelPrediction,
    ModelLifecycleStatus,
    ModelVersion,
)
from fuel_predictor.infrastructure.database import ModelVersionRow, PredictionRow, SessionFactory

# Both a fresh candidate and a previously-retired version may become active:
# the first is a promotion, the second is a rollback. The difference in
# authority between them (rollback needs an administrator and a recorded
# reason, ADR 0010) is enforced by the use case, not here — this method owns
# the concurrency contract, not the approval policy.
_ACTIVATABLE_STATUSES = frozenset(
    {ModelLifecycleStatus.CANDIDATE.value, ModelLifecycleStatus.RETIRED.value}
)


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

    def activate(
        self,
        model_version_id: str,
        expected_active_version_id: str | None,
        activated_at: datetime,
    ) -> ActivationTransition:
        """Apply the transition only if the active version still matches expectations.

        The conditional `UPDATE ... WHERE model_version_id = :expected AND
        status = 'active'` is the arbiter: a zero row count means someone else
        already changed the active model, so this caller loses. When the caller
        expects *no* active model, the partial unique index on
        `lifecycle_status = 'active'` plays the same role — two callers racing
        to be first will see one `IntegrityError`, which is reported as the
        same conflict rather than a crash.
        """
        with self._session_factory.begin() as session:
            target = session.scalar(
                select(ModelVersionRow).where(
                    ModelVersionRow.model_version_id == model_version_id
                )
            )
            if target is None:
                raise ModelVersionNotFoundError(model_version_id)
            if target.lifecycle_status == ModelLifecycleStatus.ACTIVE.value:
                # Already active and the caller expected exactly that: treat as
                # an idempotent success so a retried request is not an error.
                if expected_active_version_id == model_version_id:
                    return ActivationTransition(
                        succeeded=True,
                        active_version=_to_model(target),
                        previous_version_id=model_version_id,
                    )
                return _conflict(session)
            if target.lifecycle_status not in _ACTIVATABLE_STATUSES:
                raise ModelNotActivatableError(model_version_id, target.lifecycle_status)

            if expected_active_version_id is None:
                if session.scalar(_active_query()) is not None:
                    return _conflict(session)
            else:
                # A DML execute returns a CursorResult, whose rowcount is the
                # whole point here: zero rows means the expected version was
                # no longer the active one, so this caller lost the race.
                retired = cast(
                    "CursorResult[Any]",
                    session.execute(
                        update(ModelVersionRow)
                        .where(
                            ModelVersionRow.model_version_id == expected_active_version_id,
                            ModelVersionRow.lifecycle_status
                            == ModelLifecycleStatus.ACTIVE.value,
                        )
                        .values(
                            lifecycle_status=ModelLifecycleStatus.RETIRED.value,
                            retired_at=activated_at,
                        )
                    ),
                )
                if retired.rowcount == 0:
                    return _conflict(session)

            target.lifecycle_status = ModelLifecycleStatus.ACTIVE.value
            target.promoted_at = activated_at
            target.retired_at = None
            try:
                session.flush()
            except IntegrityError:
                # Lost the race to the partial unique index; roll this attempt
                # back so the winner's row stands, then report the conflict.
                session.rollback()
                return _conflict_in_new_session(self._session_factory)
            return ActivationTransition(
                succeeded=True,
                active_version=_to_model(target),
                previous_version_id=expected_active_version_id,
            )

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


def _active_query() -> Select[tuple[ModelVersionRow]]:
    return select(ModelVersionRow).where(
        ModelVersionRow.lifecycle_status == ModelLifecycleStatus.ACTIVE.value
    )


def _conflict(session: Session) -> ActivationTransition:
    """Report the version that is actually active, so the caller can re-read."""
    current = session.scalar(_active_query())
    return ActivationTransition(
        succeeded=False,
        active_version=_to_model(current) if current is not None else None,
    )


def _conflict_in_new_session(session_factory: SessionFactory) -> ActivationTransition:
    with session_factory() as session:
        return _conflict(session)


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
