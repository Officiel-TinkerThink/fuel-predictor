"""Prediction serves from the in-process holder once one is populated (ADR 0010).

Until an externally-ingested package is activated the holder is empty and
prediction keeps using the MLflow-backed store, which is what ADR 0011
requires while the two paths coexist.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from fuel_predictor.application.baseline_predictions import (
    BaselineModelNotFoundError,
    GenerateFuelPrediction,
)
from fuel_predictor.application.model_activation import ActiveModelHolder, LoadedModel
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


def _version(model_version_id: str) -> ModelVersion:
    return ModelVersion(
        model_version_id=model_version_id,
        version=1,
        dataset_version_id="DSV-000001",
        feature_version="baseline-v1",
        algorithm="linear_regression",
        artifact_uri=f"file:///{model_version_id}",
        trained_at=datetime(2026, 8, 22, tzinfo=UTC),
        training_row_count=10,
        uncertainty_liters=2.0,
        lifecycle_status=ModelLifecycleStatus.ACTIVE,
    )


def _operation() -> DailyOperation:
    return DailyOperation(
        operation_id="OPR-1",
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=30.0,
        distance_source=DistanceSource.MANUAL,
    )


class _OperationReader:
    def get(self, operation_id: str) -> DailyOperation | None:
        return _operation() if operation_id == "OPR-1" else None


class _ModelReader:
    def __init__(self, active: ModelVersion | None) -> None:
        self.active = active
        self.reads = 0

    def get_active(self) -> ModelVersion | None:
        self.reads += 1
        return self.active


class _Store:
    def __init__(self, answer: float = 11.0) -> None:
        self.answer = answer
        self.calls = 0

    def predict(self, artifact_uri: str, features: dict[str, Any]) -> float:
        self.calls += 1
        return self.answer

    def train(self, model_version_id: str, operations: Any) -> tuple[str, float]:
        raise AssertionError("training is not part of the serving path")


class _Writer:
    def __init__(self) -> None:
        self.written: list[Any] = []

    def add(self, prediction: Any) -> None:
        self.written.append(prediction)


class _Predictor:
    def __init__(self, answer: float) -> None:
        self.answer = answer

    def predict(self, features: dict[str, Any]) -> float:
        return self.answer


def _generator(holder: ActiveModelHolder | None, store: _Store, reader: _ModelReader) -> Any:
    return GenerateFuelPrediction(
        operation_reader=_OperationReader(),
        model_reader=reader,
        model_store=store,
        prediction_writer=_Writer(),
        safety_margin_liters=5.0,
        holder=holder,
    )


def test_an_empty_holder_falls_back_to_the_existing_model_store() -> None:
    """ADR 0011 keeps the MLflow path working until ingestion reaches parity."""
    store = _Store(answer=11.0)
    reader = _ModelReader(active=_version("MDL-MLFLOW"))

    prediction = _generator(ActiveModelHolder(), store, reader).execute("OPR-1")

    assert store.calls == 1
    assert prediction.model.model_version_id == "MDL-MLFLOW"
    assert prediction.estimated_fuel_requirement_liters == 11.0


def test_no_holder_at_all_behaves_exactly_as_before() -> None:
    store = _Store(answer=11.0)
    reader = _ModelReader(active=_version("MDL-MLFLOW"))

    prediction = _generator(None, store, reader).execute("OPR-1")

    assert prediction.model.model_version_id == "MDL-MLFLOW"


def test_a_populated_holder_serves_the_prediction_instead_of_the_store() -> None:
    store = _Store(answer=11.0)
    reader = _ModelReader(active=_version("MDL-MLFLOW"))
    holder = ActiveModelHolder(
        initial=LoadedModel(version=_version("MDL-PACKAGE"), predictor=_Predictor(23.0))
    )

    prediction = _generator(holder, store, reader).execute("OPR-1")

    assert store.calls == 0, "the resident model must be used, not reloaded per request"
    assert prediction.model.model_version_id == "MDL-PACKAGE"
    assert prediction.estimated_fuel_requirement_liters == 23.0


def test_the_reported_version_matches_the_model_that_produced_the_number() -> None:
    """Lineage must not attribute one model's estimate to another's version."""
    holder = ActiveModelHolder(
        initial=LoadedModel(version=_version("MDL-PACKAGE"), predictor=_Predictor(23.0))
    )

    prediction = _generator(holder, _Store(), _ModelReader(active=_version("MDL-OTHER"))).execute(
        "OPR-1"
    )

    assert prediction.model.model_version_id == "MDL-PACKAGE"
    assert prediction.estimated_fuel_requirement_liters == 23.0


def test_no_model_anywhere_still_raises_the_same_error() -> None:
    generator = _generator(ActiveModelHolder(), _Store(), _ModelReader(active=None))

    with pytest.raises(BaselineModelNotFoundError):
        generator.execute("OPR-1")


def test_ensure_model_available_accepts_a_holder_only_deployment() -> None:
    """A package-only deployment has no MLflow active row, and that is fine."""
    holder = ActiveModelHolder(
        initial=LoadedModel(version=_version("MDL-PACKAGE"), predictor=_Predictor(1.0))
    )

    _generator(holder, _Store(), _ModelReader(active=None)).ensure_model_available()


def test_a_swap_after_the_reference_is_taken_does_not_affect_the_running_request() -> None:
    """The holder is read once per request, so an activation mid-request is safe."""
    holder = ActiveModelHolder(
        initial=LoadedModel(version=_version("MDL-FIRST"), predictor=_Predictor(10.0))
    )
    taken = holder.current()
    holder.swap(LoadedModel(version=_version("MDL-SECOND"), predictor=_Predictor(99.0)))

    assert taken is not None
    assert taken.predict({}) == 10.0
    assert taken.version.model_version_id == "MDL-FIRST"
