from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fuel_predictor.application.actual_fuel import (
    ModelEvaluationCase,
    PerformanceMetrics,
    PredictionOutcome,
    calculate_performance_metrics,
)
from fuel_predictor.application.baseline_predictions import BaselineModelStore
from fuel_predictor.application.prediction_features import feature_values
from fuel_predictor.domain.daily_operation import VehicleCategory
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


class ModelVersionReader(Protocol):
    def get_active(self) -> ModelVersion | None: ...

    def get(self, model_version_id: str) -> ModelVersion | None: ...

    def list_candidates(self) -> Sequence[ModelVersion]: ...


class ModelPromotionWriter(Protocol):
    def promote(self, model_version_id: str, promoted_at: datetime) -> ModelVersion | None: ...


class ModelEvaluationCaseReader(Protocol):
    def get_model_evaluation_cases(self) -> Sequence[ModelEvaluationCase]: ...


class CandidateModelNotFoundError(LookupError):
    pass


class ModelPromotionNotAllowedError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CategoryModelComparison:
    vehicle_category: VehicleCategory
    candidate: PerformanceMetrics
    active: PerformanceMetrics | None


@dataclass(frozen=True, slots=True)
class ModelComparison:
    candidate: ModelVersion
    active_model: ModelVersion | None
    candidate_overall: PerformanceMetrics
    active_overall: PerformanceMetrics | None
    by_vehicle_category: tuple[CategoryModelComparison, ...]


@dataclass(frozen=True, slots=True)
class ModelGovernanceDashboard:
    active_model: ModelVersion | None
    active_performance: PerformanceMetrics | None
    candidate_models: tuple[ModelVersion, ...]
    retraining_recommended: bool
    recommendation: str


@dataclass(frozen=True, slots=True)
class PromoteCandidateModel:
    model_reader: ModelVersionReader
    model_writer: ModelPromotionWriter
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, model_version_id: str) -> ModelVersion:
        model = self.model_reader.get(model_version_id)
        if model is None:
            raise CandidateModelNotFoundError(model_version_id)
        if model.lifecycle_status is ModelLifecycleStatus.RETIRED:
            raise ModelPromotionNotAllowedError(
                "Model yang sudah dipensiunkan tidak dapat dipromosikan kembali."
            )
        promoted = self.model_writer.promote(model_version_id, self.now())
        if promoted is None:
            raise CandidateModelNotFoundError(model_version_id)
        return promoted


@dataclass(frozen=True, slots=True)
class GetCandidateModelComparison:
    model_reader: ModelVersionReader
    evaluation_reader: ModelEvaluationCaseReader
    model_store: BaselineModelStore

    def execute(self, candidate_model_version_id: str) -> ModelComparison:
        candidate = self.model_reader.get(candidate_model_version_id)
        if candidate is None or candidate.lifecycle_status is not ModelLifecycleStatus.CANDIDATE:
            raise CandidateModelNotFoundError(candidate_model_version_id)
        active = self.model_reader.get_active()
        cases = tuple(self.evaluation_reader.get_model_evaluation_cases())
        candidate_outcomes = _outcomes_for_model(candidate, cases, self.model_store)
        active_outcomes = _outcomes_for_model(active, cases, self.model_store) if active else None
        categories = tuple(sorted({case.operation.vehicle_category for case in cases}, key=str))
        return ModelComparison(
            candidate=candidate,
            active_model=active,
            candidate_overall=calculate_performance_metrics(candidate_outcomes),
            active_overall=(
                calculate_performance_metrics(active_outcomes)
                if active_outcomes is not None
                else None
            ),
            by_vehicle_category=tuple(
                CategoryModelComparison(
                    vehicle_category=category,
                    candidate=calculate_performance_metrics(
                        tuple(
                            outcome
                            for outcome in candidate_outcomes
                            if outcome.vehicle_category is category
                        )
                    ),
                    active=(
                        calculate_performance_metrics(
                            tuple(
                                outcome
                                for outcome in active_outcomes
                                if outcome.vehicle_category is category
                            )
                        )
                        if active_outcomes is not None
                        else None
                    ),
                )
                for category in categories
            ),
        )


@dataclass(frozen=True, slots=True)
class GetModelGovernanceDashboard:
    model_reader: ModelVersionReader
    evaluation_reader: ModelEvaluationCaseReader
    model_store: BaselineModelStore
    max_active_model_mae_liters: float

    def execute(self) -> ModelGovernanceDashboard:
        active = self.model_reader.get_active()
        candidates = tuple(self.model_reader.list_candidates())
        active_performance = None
        if active is not None:
            active_performance = calculate_performance_metrics(
                _outcomes_for_model(
                    active,
                    tuple(self.evaluation_reader.get_model_evaluation_cases()),
                    self.model_store,
                )
            )
        retraining_recommended = bool(
            active_performance
            and active_performance.mae_liters is not None
            and active_performance.mae_liters > self.max_active_model_mae_liters
        )
        if active is None:
            recommendation = (
                "Belum ada model aktif. Latih kandidat dari dataset tervalidasi lalu promosikan "
                "secara manual setelah ditinjau."
            )
        elif retraining_recommended:
            recommendation = (
                "Kinerja model aktif perlu ditinjau. Latih kandidat baru secara manual dan "
                "bandingkan metriknya sebelum promosi."
            )
        elif candidates:
            recommendation = (
                "Kandidat tersedia untuk ditinjau. Perbandingan dan promosi tetap merupakan "
                "tindakan manual."
            )
        else:
            recommendation = "Belum ada rekomendasi pelatihan ulang berdasarkan evaluasi saat ini."
        return ModelGovernanceDashboard(
            active_model=active,
            active_performance=active_performance,
            candidate_models=candidates,
            retraining_recommended=retraining_recommended,
            recommendation=recommendation,
        )


def _outcomes_for_model(
    model: ModelVersion,
    cases: Sequence[ModelEvaluationCase],
    model_store: BaselineModelStore,
) -> tuple[PredictionOutcome, ...]:
    outcomes = []
    for case in cases:
        estimate = max(0.0, model_store.predict(model.artifact_uri, feature_values(case.operation)))
        outcomes.append(
            PredictionOutcome(
                vehicle_category=case.operation.vehicle_category,
                estimated_fuel_requirement_liters=estimate,
                uncertainty_lower_liters=max(0.0, estimate - model.uncertainty_liters),
                uncertainty_upper_liters=estimate + model.uncertainty_liters,
                actual_fuel_liters=case.actual_fuel_liters,
            )
        )
    return tuple(outcomes)
