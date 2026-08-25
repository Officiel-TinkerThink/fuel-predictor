"""The conditional-UPDATE activation repository (ADR 0010).

Runs against a real SQLite database rather than a fake, because the whole
point of these tests is the database-level concurrency contract: the partial
unique index and the zero-row conditional UPDATE are what make the database
the arbiter, and a fake repository cannot demonstrate either.
"""

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from fuel_predictor.domain.model_activation import (
    ModelNotActivatableError,
    ModelVersionNotFoundError,
)
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_predictions import SqlAlchemyPredictionRepository

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _candidate(model_version_id: str) -> ModelVersion:
    return ModelVersion(
        model_version_id=model_version_id,
        version=0,
        dataset_version_id="DSV-000001",
        feature_version="baseline-v1",
        algorithm="linear_regression",
        artifact_uri=f"file:///models/{model_version_id}",
        trained_at=_NOW,
        training_row_count=10,
        uncertainty_liters=2.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'models.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    factory = build_session_factory(engine)
    # model_versions has a foreign key to dataset_versions, so seed one row.
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO dataset_versions (dataset_version_id, source_filename, imported_at,"
                " valid_operation_count, quarantined_row_count, ignored_blank_row_count)"
                " VALUES ('DSV-000001', 'seed.csv', :now, 10, 0, 0)"
            ),
            {"now": _NOW},
        )
    return factory


@pytest.fixture
def repository(session_factory: sessionmaker[Session]) -> SqlAlchemyPredictionRepository:
    return SqlAlchemyPredictionRepository(session_factory)


def test_activating_the_first_model_expects_no_current_active(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    repository.create(_candidate("MDL-FIRST"))

    transition = repository.activate("MDL-FIRST", None, _NOW)

    assert transition.succeeded is True
    assert transition.active_version is not None
    assert transition.active_version.lifecycle_status is ModelLifecycleStatus.ACTIVE
    assert transition.previous_version_id is None
    active = repository.get_active()
    assert active is not None and active.model_version_id == "MDL-FIRST"


def test_activation_retires_the_previous_active_model(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    repository.create(_candidate("MDL-OLD"))
    repository.create(_candidate("MDL-NEW"))
    repository.activate("MDL-OLD", None, _NOW)

    transition = repository.activate("MDL-NEW", "MDL-OLD", _NOW)

    assert transition.succeeded is True
    assert transition.previous_version_id == "MDL-OLD"
    retired = repository.get("MDL-OLD")
    assert retired is not None
    assert retired.lifecycle_status is ModelLifecycleStatus.RETIRED
    assert retired.retired_at is not None


def test_a_stale_expected_version_loses_and_learns_what_is_actually_active(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    repository.create(_candidate("MDL-A"))
    repository.create(_candidate("MDL-B"))
    repository.create(_candidate("MDL-C"))
    repository.activate("MDL-A", None, _NOW)
    repository.activate("MDL-B", "MDL-A", _NOW)

    transition = repository.activate("MDL-C", "MDL-A", _NOW)

    assert transition.succeeded is False
    assert transition.active_version is not None
    assert transition.active_version.model_version_id == "MDL-B"
    still_candidate = repository.get("MDL-C")
    assert still_candidate is not None
    assert still_candidate.lifecycle_status is ModelLifecycleStatus.CANDIDATE


def test_expecting_no_active_model_when_one_exists_is_a_conflict(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    repository.create(_candidate("MDL-A"))
    repository.create(_candidate("MDL-B"))
    repository.activate("MDL-A", None, _NOW)

    transition = repository.activate("MDL-B", None, _NOW)

    assert transition.succeeded is False
    assert transition.active_version is not None
    assert transition.active_version.model_version_id == "MDL-A"


def test_reactivating_the_already_active_version_is_idempotent(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    """A retried request must not be reported as a conflict with itself."""
    repository.create(_candidate("MDL-A"))
    repository.activate("MDL-A", None, _NOW)

    transition = repository.activate("MDL-A", "MDL-A", _NOW)

    assert transition.succeeded is True
    assert transition.active_version is not None
    assert transition.active_version.model_version_id == "MDL-A"


def test_a_retired_version_can_be_reactivated_for_rollback(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    """Rollback re-activates a retained version through this same path (ADR 0010).

    The extra authority rollback requires — an administrator and a recorded
    reason — is the use case's job, not this method's.
    """
    repository.create(_candidate("MDL-GOOD"))
    repository.create(_candidate("MDL-BAD"))
    repository.activate("MDL-GOOD", None, _NOW)
    repository.activate("MDL-BAD", "MDL-GOOD", _NOW)

    transition = repository.activate("MDL-GOOD", "MDL-BAD", _NOW)

    assert transition.succeeded is True
    restored = repository.get("MDL-GOOD")
    assert restored is not None
    assert restored.lifecycle_status is ModelLifecycleStatus.ACTIVE
    assert restored.retired_at is None, "a restored model must not still look retired"


def test_activating_a_version_that_does_not_exist_is_not_a_conflict(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    with pytest.raises(ModelVersionNotFoundError):
        repository.activate("MDL-GHOST", None, _NOW)


def test_only_one_of_two_racing_activations_can_win(
    repository: SqlAlchemyPredictionRepository,
) -> None:
    """Two callers with the same expectation; the database picks the winner."""
    repository.create(_candidate("MDL-BASE"))
    repository.create(_candidate("MDL-X"))
    repository.create(_candidate("MDL-Y"))
    repository.activate("MDL-BASE", None, _NOW)

    started = threading.Barrier(2)
    results: list[bool] = []
    results_lock = threading.Lock()

    def attempt(candidate_id: str) -> None:
        started.wait(timeout=5)
        try:
            transition = repository.activate(candidate_id, "MDL-BASE", _NOW)
            succeeded = transition.succeeded
        except Exception:  # noqa: BLE001 - a losing racer must not crash the test
            succeeded = False
        with results_lock:
            results.append(succeeded)

    threads = [
        threading.Thread(target=attempt, args=("MDL-X",)),
        threading.Thread(target=attempt, args=("MDL-Y",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert sum(results) == 1, f"exactly one activation must win, got {results}"
    active = repository.get_active()
    assert active is not None
    assert active.model_version_id in {"MDL-X", "MDL-Y"}


def test_two_candidates_racing_for_an_empty_slot_produce_one_active(
    repository: SqlAlchemyPredictionRepository,
    session_factory: sessionmaker[Session],
) -> None:
    """Both callers expect *no* active model, so the arbiter is the index.

    The other race test has both callers naming the same expected version, so
    the conditional UPDATE decides it. When `expected_active_version_id` is
    None there is no row to conditionally update, and the partial unique index
    on `lifecycle_status = 'active'` is what stops both from winning — a
    different branch, reached only by racing on an empty slot.
    """
    repository.create(_candidate("MDL-P"))
    repository.create(_candidate("MDL-Q"))

    started = threading.Barrier(2)
    results: list[bool] = []
    results_lock = threading.Lock()

    def attempt(candidate_id: str) -> None:
        started.wait(timeout=5)
        try:
            succeeded = repository.activate(candidate_id, None, _NOW).succeeded
        except Exception:  # noqa: BLE001 - a losing racer must not crash the test
            succeeded = False
        with results_lock:
            results.append(succeeded)

    threads = [
        threading.Thread(target=attempt, args=("MDL-P",)),
        threading.Thread(target=attempt, args=("MDL-Q",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert sum(results) == 1, f"exactly one activation must win, got {results}"
    # Asserted against the table, not the repository: this holds whatever the
    # interleaving turned out to be, including the case where the threads did
    # not genuinely overlap.
    with session_factory() as session:
        active = [
            row[0]
            for row in session.execute(
                text(
                    "SELECT model_version_id FROM model_versions"
                    " WHERE lifecycle_status = 'active'"
                )
            )
        ]
    assert active in (["MDL-P"], ["MDL-Q"]), active


def test_a_version_in_an_unactivatable_state_is_refused(
    repository: SqlAlchemyPredictionRepository,
    session_factory: sessionmaker[Session],
) -> None:
    """Guards the lifecycle states this code does not know how to activate.

    Unreachable through `ModelLifecycleStatus` today, since its three values
    are all handled. It exists because the production plan's state diagram
    adds `rejected`, and a rejected package must never become active by
    accident. Driven here by writing the status directly, so the guard is
    genuinely exercised rather than being untested defensive code.
    """
    repository.create(_candidate("MDL-REJECTED"))
    with session_factory.begin() as session:
        session.execute(
            text(
                "UPDATE model_versions SET lifecycle_status = 'rejected'"
                " WHERE model_version_id = 'MDL-REJECTED'"
            )
        )

    with pytest.raises(ModelNotActivatableError) as excinfo:
        repository.activate("MDL-REJECTED", None, _NOW)

    assert excinfo.value.lifecycle_status == "rejected"


def test_exactly_one_model_is_active_after_a_chain_of_activations(
    repository: SqlAlchemyPredictionRepository,
    session_factory: sessionmaker[Session],
) -> None:
    """The core invariant, asserted against the database rather than inferred."""
    for name in ("MDL-1", "MDL-2", "MDL-3"):
        repository.create(_candidate(name))
    repository.activate("MDL-1", None, _NOW)
    repository.activate("MDL-2", "MDL-1", _NOW)
    repository.activate("MDL-3", "MDL-2", _NOW)

    # A stale expectation loses without disturbing the active row. MDL-1 is
    # retired so it is a legitimate rollback *target*, but the caller believes
    # MDL-1 is still active when MDL-3 actually is.
    transition = repository.activate("MDL-1", "MDL-1", _NOW)
    assert transition.succeeded is False
    assert transition.active_version is not None
    assert transition.active_version.model_version_id == "MDL-3"

    with session_factory() as session:
        active_count = session.scalar(
            text("SELECT COUNT(*) FROM model_versions WHERE lifecycle_status = 'active'")
        )
    assert active_count == 1
