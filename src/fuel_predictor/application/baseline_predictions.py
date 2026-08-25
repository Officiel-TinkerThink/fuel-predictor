from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from fuel_predictor.application.daily_operations import (
    DailyOperationNotFoundError,
    DailyOperationReader,
)
from fuel_predictor.application.historical_datasets import (
    DatasetVersionNotFoundError,
    HistoricalDatasetReader,
)
from fuel_predictor.application.prediction_features import (
    FEATURE_VERSION,
    feature_values,
    input_snapshot,
)
from fuel_predictor.domain.historical_dataset import HistoricalDailyOperation
from fuel_predictor.domain.prediction import FuelPrediction, ModelLifecycleStatus, ModelVersion

if TYPE_CHECKING:
    from fuel_predictor.application.model_activation import ActiveModelHolder, LoadedModel


class BaselineModelStore(Protocol):
    def train(
        self, model_version_id: str, operations: Sequence[HistoricalDailyOperation]
    ) -> tuple[str, float]: ...

    def predict(self, artifact_uri: str, features: dict[str, str | float]) -> float: ...


class ModelVersionWriter(Protocol):
    def create(self, model: ModelVersion) -> ModelVersion: ...


class ActiveModelVersionReader(Protocol):
    def get_active(self) -> ModelVersion | None: ...


class PredictionWriter(Protocol):
    def add(self, prediction: FuelPrediction) -> None: ...


class BaselineTrainingError(ValueError):
    pass


class BaselineModelNotFoundError(LookupError):
    """No trained model is available to serve a prediction.

    Carries its own message so callers that surface the exception generically
    — the MCP tool surface, logs — still say something an operator can act on.
    The HTTP and page handlers override it with their own wording.
    """

    def __init__(
        self,
        message: str = "Belum ada kandidat baseline terlatih untuk membuat prediksi.",
    ) -> None:
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class TrainBaselineCandidate:
    dataset_reader: HistoricalDatasetReader
    model_store: BaselineModelStore
    model_writer: ModelVersionWriter
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, dataset_version_id: str) -> ModelVersion:
        operations = self.dataset_reader.get_valid_operations(dataset_version_id)
        if operations is None:
            raise DatasetVersionNotFoundError(dataset_version_id)
        if len(operations) < 2:
            raise BaselineTrainingError(
                "Dataset perlu sedikitnya dua operasi valid untuk pelatihan."
            )
        model_version_id = f"MDL-{uuid4().hex.upper()}"
        artifact_uri, uncertainty_liters = self.model_store.train(model_version_id, operations)
        model = ModelVersion(
            model_version_id=model_version_id,
            version=0,
            dataset_version_id=dataset_version_id,
            feature_version=FEATURE_VERSION,
            algorithm="linear_regression",
            artifact_uri=artifact_uri,
            trained_at=self.now(),
            training_row_count=len(operations),
            uncertainty_liters=uncertainty_liters,
            lifecycle_status=ModelLifecycleStatus.CANDIDATE,
        )
        return self.model_writer.create(model)


@dataclass(frozen=True, slots=True)
class GenerateFuelPrediction:
    operation_reader: DailyOperationReader
    model_reader: ActiveModelVersionReader
    model_store: BaselineModelStore
    prediction_writer: PredictionWriter
    safety_margin_liters: float
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    # Set once an externally-ingested package has been activated (ADR 0010).
    # While it is empty, prediction keeps using the MLflow-backed store, which
    # is what ADR 0011 requires until package ingestion reaches parity.
    holder: "ActiveModelHolder | None" = None

    def ensure_model_available(self) -> None:
        if self._resident_model() is None and self.model_reader.get_active() is None:
            raise BaselineModelNotFoundError()

    def execute(self, operation_id: str) -> FuelPrediction:
        operation = self.operation_reader.get(operation_id)
        if operation is None:
            raise DailyOperationNotFoundError(operation_id)
        features = feature_values(operation)

        # Read the holder exactly once and keep that reference for the rest of
        # the request (ADR 0010): an activation swapping mid-request must not
        # make this prediction attribute one model's numbers to another's
        # version.
        resident = self._resident_model()
        if resident is not None:
            model = resident.version
            estimate = max(0.0, resident.predict(features))
        else:
            active = self.model_reader.get_active()
            if active is None:
                raise BaselineModelNotFoundError()
            model = active
            estimate = max(0.0, self.model_store.predict(model.artifact_uri, features))
        lower = max(0.0, estimate - model.uncertainty_liters)
        upper = estimate + model.uncertainty_liters
        recommended = max(estimate, upper, estimate + self.safety_margin_liters)
        prediction = FuelPrediction(
            prediction_id=f"PRD-{uuid4().hex.upper()}",
            operation_id=operation.operation_id,
            model=model,
            estimated_fuel_requirement_liters=estimate,
            recommended_allocation_liters=recommended,
            uncertainty_lower_liters=lower,
            uncertainty_upper_liters=upper,
            route_distance_source=operation.distance_source,
            route_distance_manual_fallback=operation.route_distance_manual_fallback,
            safety_policy=(
                "Alokasi rekomendasi mengikuti kebijakan awal: tambah margin konservatif "
                f"{self.safety_margin_liters:g} L atau batas atas ketidakpastian. Ini bukan "
                "jaminan 99% dan belum dikalibrasi dengan bahan bakar aktual."
            ),
            input_snapshot=input_snapshot(operation),
            feature_values=features,
            created_at=self.now(),
        )
        self.prediction_writer.add(prediction)
        return prediction

    def _resident_model(self) -> "LoadedModel | None":
        return self.holder.current() if self.holder is not None else None
