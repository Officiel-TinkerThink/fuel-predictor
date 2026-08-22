"""Activation sequence and holder behaviour (ADR 0010)."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from fuel_predictor.application.model_activation import (
    ActivateModelVersion,
    ActivationTransition,
    ActiveModelHolder,
    LoadedModel,
    RollbackModelVersion,
)
from fuel_predictor.domain.model_activation import (
    ModelActivationConflictError,
    ModelCapacityError,
    ModelLoadFailedError,
    ModelSmokeTestFailedError,
    ModelVersionNotFoundError,
    PostActivationHealthCheckFailedError,
)
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


def _version(model_version_id: str) -> ModelVersion:
    return ModelVersion(
        model_version_id=model_version_id,
        version=1,
        dataset_version_id="DSV-000001",
        feature_version="baseline-v1",
        algorithm="linear_regression",
        artifact_uri=f"file:///models/{model_version_id}",
        trained_at=datetime(2026, 8, 22, tzinfo=UTC),
        training_row_count=10,
        uncertainty_liters=2.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )


class _StubPredictor:
    def __init__(self, answer: float = 10.0) -> None:
        self.answer = answer

    def predict(self, features: dict[str, str | float]) -> float:
        return self.answer


class _StubLoader:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.load_count = 0

    def load(self, version: ModelVersion) -> LoadedModel:
        self.load_count += 1
        if self.error is not None:
            raise self.error
        return LoadedModel(version=version, predictor=_StubPredictor())


class _StubSmokeTests:
    def __init__(self, failures: Sequence[str] = ()) -> None:
        self.failures = tuple(failures)

    def run(self, loaded: LoadedModel) -> Sequence[str]:
        return self.failures


class _StubMemory:
    def __init__(self, available: int = 10**12) -> None:
        self.available = available

    def available_bytes(self) -> int:
        return self.available


@dataclass
class _FakeRepository:
    """Minimal stand-in for the conditional-UPDATE repository."""

    active_version_id: str | None = None
    lock: Any = None

    def __post_init__(self) -> None:
        self.lock = threading.Lock()
        self.successful_activations: list[str] = []

    def activate(
        self,
        model_version_id: str,
        expected_active_version_id: str | None,
        activated_at: datetime,
    ) -> ActivationTransition:
        with self.lock:
            if self.active_version_id != expected_active_version_id:
                current = _version(self.active_version_id) if self.active_version_id else None
                return ActivationTransition(succeeded=False, active_version=current)
            previous = self.active_version_id
            self.active_version_id = model_version_id
            self.successful_activations.append(model_version_id)
            return ActivationTransition(
                succeeded=True,
                active_version=replace(
                    _version(model_version_id), lifecycle_status=ModelLifecycleStatus.ACTIVE
                ),
                previous_version_id=previous,
            )


def _activator(**overrides: Any) -> ActivateModelVersion:
    defaults: dict[str, Any] = {
        "holder": ActiveModelHolder(),
        "loader": _StubLoader(),
        "smoke_tests": _StubSmokeTests(),
        "repository": _FakeRepository(),
        "memory_probe": _StubMemory(),
        "health_check": lambda loaded: None,
    }
    defaults.update(overrides)
    return ActivateModelVersion(**defaults)


def test_successful_activation_swaps_the_holder_and_reports_the_previous_version() -> None:
    holder = ActiveModelHolder()
    repository = _FakeRepository(active_version_id="MDL-OLD")
    activator = _activator(holder=holder, repository=repository)

    result = activator.execute(_version("MDL-NEW"), "MDL-OLD", required_memory_bytes=1000)

    assert result.activated.model_version_id == "MDL-NEW"
    assert result.activated.lifecycle_status is ModelLifecycleStatus.ACTIVE
    assert result.previous_version_id == "MDL-OLD"
    current = holder.current()
    assert current is not None
    assert current.version.model_version_id == "MDL-NEW"


def test_activation_into_an_empty_holder_expects_no_current_version() -> None:
    holder = ActiveModelHolder()
    activator = _activator(holder=holder, repository=_FakeRepository(active_version_id=None))

    result = activator.execute(_version("MDL-FIRST"), None, required_memory_bytes=1000)

    assert result.activated.model_version_id == "MDL-FIRST"
    assert result.previous_version_id is None


def test_expected_version_mismatch_is_a_conflict_naming_the_actual_active_version() -> None:
    holder = ActiveModelHolder()
    repository = _FakeRepository(active_version_id="MDL-SOMEONE-ELSE-ACTIVATED")
    activator = _activator(holder=holder, repository=repository)

    with pytest.raises(ModelActivationConflictError) as excinfo:
        activator.execute(_version("MDL-NEW"), "MDL-STALE-BELIEF", required_memory_bytes=1000)

    assert excinfo.value.expected == "MDL-STALE-BELIEF"
    assert excinfo.value.actual == "MDL-SOMEONE-ELSE-ACTIVATED"
    assert holder.current() is None, "a losing activation must not swap the holder"


def test_insufficient_memory_is_rejected_before_the_candidate_is_even_loaded() -> None:
    loader = _StubLoader()
    activator = _activator(loader=loader, memory_probe=_StubMemory(available=1000))

    with pytest.raises(ModelCapacityError) as excinfo:
        activator.execute(_version("MDL-BIG"), None, required_memory_bytes=999_999)

    assert excinfo.value.available_bytes == 1000
    assert loader.load_count == 0, "capacity must be checked before loading, not after"


def test_a_candidate_that_fails_to_load_leaves_the_previous_model_active() -> None:
    previous = LoadedModel(version=_version("MDL-OLD"), predictor=_StubPredictor(7.0))
    holder = ActiveModelHolder(initial=previous)
    activator = _activator(
        holder=holder,
        loader=_StubLoader(error=RuntimeError("corrupt artefact")),
        repository=_FakeRepository(active_version_id="MDL-OLD"),
    )

    with pytest.raises(ModelLoadFailedError):
        activator.execute(_version("MDL-BROKEN"), "MDL-OLD", required_memory_bytes=1000)

    assert holder.current() is previous


def test_a_candidate_that_fails_smoke_tests_is_never_persisted_or_swapped() -> None:
    previous = LoadedModel(version=_version("MDL-OLD"), predictor=_StubPredictor(7.0))
    holder = ActiveModelHolder(initial=previous)
    repository = _FakeRepository(active_version_id="MDL-OLD")
    activator = _activator(
        holder=holder,
        smoke_tests=_StubSmokeTests(["case 3 expected 12.0, got 41.9"]),
        repository=repository,
    )

    with pytest.raises(ModelSmokeTestFailedError) as excinfo:
        activator.execute(_version("MDL-WRONG"), "MDL-OLD", required_memory_bytes=1000)

    assert "case 3" in str(excinfo.value)
    assert holder.current() is previous
    assert repository.active_version_id == "MDL-OLD"
    assert repository.successful_activations == []


def test_a_failed_post_activation_health_check_reports_loudly_without_reverting() -> None:
    """ADR 0010 is explicit that this must not auto-revert.

    The swap already happened and the database already committed it. Silently
    rolling back would leave a system that looks healthy while hiding that a
    promoted model is misbehaving, so the failure is surfaced and rollback is
    left to the operator as a deliberate decision.
    """
    holder = ActiveModelHolder()
    repository = _FakeRepository(active_version_id=None)
    activator = _activator(
        holder=holder,
        repository=repository,
        health_check=lambda loaded: "latensi prediksi 12s",
    )

    with pytest.raises(PostActivationHealthCheckFailedError) as excinfo:
        activator.execute(_version("MDL-SLOW"), None, required_memory_bytes=1000)

    assert excinfo.value.activated_version == "MDL-SLOW"
    current = holder.current()
    assert current is not None
    assert current.version.model_version_id == "MDL-SLOW", "must not silently revert"
    assert repository.active_version_id == "MDL-SLOW"


def test_concurrent_activations_cannot_both_win() -> None:
    """The database decides, not whichever thread happens to swap last.

    Both threads pass the same `expected_active_version_id`, so exactly one
    conditional UPDATE can match. The loser must raise a conflict and must
    not leave its candidate in the holder.
    """
    holder = ActiveModelHolder()
    repository = _FakeRepository(active_version_id="MDL-OLD")
    activator = _activator(holder=holder, repository=repository)

    started = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def attempt(candidate_id: str) -> None:
        started.wait(timeout=5)
        try:
            activator.execute(_version(candidate_id), "MDL-OLD", required_memory_bytes=1000)
            record = f"{candidate_id}:won"
        except ModelActivationConflictError:
            record = f"{candidate_id}:conflict"
        with outcomes_lock:
            outcomes.append(record)

    threads = [
        threading.Thread(target=attempt, args=("MDL-A",)),
        threading.Thread(target=attempt, args=("MDL-B",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    winners = [outcome for outcome in outcomes if outcome.endswith(":won")]
    conflicts = [outcome for outcome in outcomes if outcome.endswith(":conflict")]
    assert len(winners) == 1, outcomes
    assert len(conflicts) == 1, outcomes
    assert len(repository.successful_activations) == 1

    current = holder.current()
    assert current is not None
    assert current.version.model_version_id == winners[0].split(":")[0]


class _RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, str | None]] = []

    def record_rollback(
        self, target_version_id: str, previous_version_id: str | None, actor: str, reason: str
    ) -> None:
        self.entries.append(
            {
                "target": target_version_id,
                "previous": previous_version_id,
                "actor": actor,
                "reason": reason,
            }
        )


class _RetainedReader:
    def __init__(self, known: dict[str, ModelVersion]) -> None:
        self.known = known

    def get(self, model_version_id: str) -> ModelVersion | None:
        return self.known.get(model_version_id)


def _rollback(**overrides: Any) -> RollbackModelVersion:
    defaults: dict[str, Any] = {
        "activate": _activator(),
        "retained_reader": _RetainedReader({"MDL-GOOD": _version("MDL-GOOD")}),
        "audit": _RecordingAudit(),
    }
    defaults.update(overrides)
    return RollbackModelVersion(**defaults)


def test_rollback_reactivates_the_retained_version_and_records_who_and_why() -> None:
    holder = ActiveModelHolder()
    audit = _RecordingAudit()
    rollback = _rollback(
        activate=_activator(holder=holder, repository=_FakeRepository(active_version_id="MDL-BAD")),
        audit=audit,
    )

    result = rollback.execute(
        target_version_id="MDL-GOOD",
        expected_active_version_id="MDL-BAD",
        actor="admin",
        reason="MAE naik tajam setelah aktivasi",
        required_memory_bytes=1000,
    )

    assert result.activated.model_version_id == "MDL-GOOD"
    assert audit.entries == [
        {
            "target": "MDL-GOOD",
            "previous": "MDL-BAD",
            "actor": "admin",
            "reason": "MAE naik tajam setelah aktivasi",
        }
    ]


def test_rollback_without_a_reason_is_refused() -> None:
    audit = _RecordingAudit()
    rollback = _rollback(audit=audit)

    with pytest.raises(ValueError, match="Alasan"):
        rollback.execute(
            target_version_id="MDL-GOOD",
            expected_active_version_id=None,
            actor="admin",
            reason="   ",
            required_memory_bytes=1000,
        )

    assert audit.entries == [], "nothing should be recorded for a refused rollback"


def test_rollback_to_an_unknown_version_is_refused_before_anything_is_recorded() -> None:
    audit = _RecordingAudit()
    rollback = _rollback(audit=audit)

    with pytest.raises(ModelVersionNotFoundError):
        rollback.execute(
            target_version_id="MDL-NEVER-EXISTED",
            expected_active_version_id=None,
            actor="admin",
            reason="mencoba memulihkan",
            required_memory_bytes=1000,
        )

    assert audit.entries == []


def test_the_rollback_intent_is_recorded_even_when_the_activation_then_loses() -> None:
    """The decision is worth keeping even if the attempt fails.

    Someone reconstructing an incident later needs to see that a rollback was
    attempted and why, not just that the active model never changed.
    """
    audit = _RecordingAudit()
    rollback = _rollback(
        activate=_activator(repository=_FakeRepository(active_version_id="MDL-SOMEONE-ELSE")),
        audit=audit,
    )

    with pytest.raises(ModelActivationConflictError):
        rollback.execute(
            target_version_id="MDL-GOOD",
            expected_active_version_id="MDL-STALE",
            actor="admin",
            reason="kembali ke versi stabil",
            required_memory_bytes=1000,
        )

    assert len(audit.entries) == 1
    assert audit.entries[0]["reason"] == "kembali ke versi stabil"


def test_holder_reads_are_stable_across_a_concurrent_swap() -> None:
    """A reference taken before a swap stays usable after it.

    This is what lets an in-flight prediction finish under the model it
    started with instead of seeing a half-changed world.
    """
    first = LoadedModel(version=_version("MDL-FIRST"), predictor=_StubPredictor(1.0))
    second = LoadedModel(version=_version("MDL-SECOND"), predictor=_StubPredictor(2.0))
    holder = ActiveModelHolder(initial=first)

    taken = holder.current()
    holder.swap(second)

    assert taken is not None
    assert taken.version.model_version_id == "MDL-FIRST"
    assert taken.predict({}) == 1.0
    current = holder.current()
    assert current is not None
    assert current.version.model_version_id == "MDL-SECOND"
