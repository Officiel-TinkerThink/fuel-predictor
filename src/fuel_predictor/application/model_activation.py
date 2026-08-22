"""In-process active-model holder and the activation sequence (ADR 0010).

The holder keeps one loaded model resident so prediction never pays load
cost per request, and activation swaps that reference only after the
database has agreed the transition is allowed. The database is the arbiter,
not the in-memory state: two concurrent activations cannot both win, because
only one of them gets a committed row change.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fuel_predictor.domain.model_activation import (
    ModelActivationConflictError,
    ModelCapacityError,
    ModelLoadFailedError,
    ModelSmokeTestFailedError,
    PostActivationHealthCheckFailedError,
)
from fuel_predictor.domain.prediction import ModelVersion


@dataclass(frozen=True, slots=True)
class LoadedModel:
    """A model held in memory together with the version it was loaded from.

    Kept as one immutable pair so a reader can never observe a model from one
    version alongside metadata from another: swapping the pair is a single
    reference rebind.
    """

    version: ModelVersion
    predictor: Any

    def predict(self, features: dict[str, str | float]) -> float:
        result = self.predictor.predict(features)
        return float(result)


class ModelArtifactLoader(Protocol):
    """Loads and warms a model artefact. Raises on anything it cannot load."""

    def load(self, version: ModelVersion) -> LoadedModel: ...


class SmokeTestRunner(Protocol):
    """Runs a candidate's own declared smoke tests against the loaded model.

    Returns a description of each failure; an empty sequence means the
    candidate answered every declared case correctly.
    """

    def run(self, loaded: LoadedModel) -> Sequence[str]: ...


class MemoryProbe(Protocol):
    def available_bytes(self) -> int: ...


class ActivationRepository(Protocol):
    """Persists the lifecycle transition under optimistic concurrency.

    `activate` must apply the transition only if the currently-active version
    still matches `expected_active_version_id`, and must report the actual
    active version when it does not — a zero-row conditional UPDATE, not a
    read-then-write.
    """

    def activate(
        self,
        model_version_id: str,
        expected_active_version_id: str | None,
        activated_at: datetime,
    ) -> "ActivationTransition": ...


@dataclass(frozen=True, slots=True)
class ActivationTransition:
    """Result of the persisted transition attempt."""

    succeeded: bool
    active_version: ModelVersion | None
    previous_version_id: str | None = None


class ActiveModelHolder:
    """Holds the current model, swappable without interrupting readers.

    Reads are lock-free: `current()` returns whatever reference is bound at
    that moment, and a request that took a reference keeps using it even if a
    swap happens mid-request. Rebinding one attribute is atomic in CPython, so
    a reader can never see a half-updated pair.

    Writes are serialised by a separate lock so only one activation loads and
    warms a candidate at a time — that is the expensive, memory-hungry part,
    and running two at once is what the capacity check is trying to prevent.
    """

    def __init__(self, initial: LoadedModel | None = None) -> None:
        self._current = initial
        self._activation_lock = threading.Lock()

    def current(self) -> LoadedModel | None:
        return self._current

    def swap(self, loaded: LoadedModel) -> LoadedModel | None:
        previous = self._current
        self._current = loaded
        return previous

    @property
    def activation_lock(self) -> threading.Lock:
        return self._activation_lock


@dataclass(frozen=True, slots=True)
class ActivationResult:
    activated: ModelVersion
    previous_version_id: str | None


@dataclass(frozen=True, slots=True)
class ActivateModelVersion:
    """The ordered activation sequence from ADR 0010.

    Load and warm, smoke-test, persist under optimistic concurrency, swap,
    health-check. Every failure before the swap leaves the previous model
    both active and loaded; a failure *after* the swap is reported loudly and
    never silently reverted.
    """

    holder: ActiveModelHolder
    loader: ModelArtifactLoader
    smoke_tests: SmokeTestRunner
    repository: ActivationRepository
    memory_probe: MemoryProbe
    health_check: Callable[[LoadedModel], str | None]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self,
        candidate: ModelVersion,
        expected_active_version_id: str | None,
        required_memory_bytes: int,
    ) -> ActivationResult:
        with self.holder.activation_lock:
            self._reject_if_insufficient_memory(required_memory_bytes)

            try:
                loaded = self.loader.load(candidate)
            except Exception as error:  # noqa: BLE001 - reported as a domain failure
                raise ModelLoadFailedError(str(error)) from error

            failures = tuple(self.smoke_tests.run(loaded))
            if failures:
                raise ModelSmokeTestFailedError(failures)

            transition = self.repository.activate(
                candidate.model_version_id, expected_active_version_id, self.now()
            )
            if not transition.succeeded or transition.active_version is None:
                actual = (
                    transition.active_version.model_version_id
                    if transition.active_version
                    else None
                )
                raise ModelActivationConflictError(expected_active_version_id, actual)

            # Only now, after the database has committed the transition, does
            # the in-memory reference move. Doing it earlier would let a
            # losing concurrent activation still serve its candidate.
            activated = transition.active_version
            swapped_in = LoadedModel(version=activated, predictor=loaded.predictor)
            self.holder.swap(swapped_in)
            result = ActivationResult(
                activated=activated,
                previous_version_id=transition.previous_version_id,
            )

        # Health-check the model this activation swapped in, not whatever the
        # holder happens to contain now: the lock is released, so a later
        # activation may already have replaced it, and blaming this call for
        # that model's health would be wrong.
        problem = self.health_check(swapped_in)
        if problem is not None:
            raise PostActivationHealthCheckFailedError(activated.model_version_id, problem)
        return result

    def _reject_if_insufficient_memory(self, required_bytes: int) -> None:
        available = self.memory_probe.available_bytes()
        if required_bytes > available:
            raise ModelCapacityError(required_bytes, available)
