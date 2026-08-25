"""Retention must never delete a rollback target (ADR 0010).

Freeing disk by removing the version an operator would fall back to has not
tidied anything — it has removed the recovery path, and nobody finds out until
the day they need it.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fuel_predictor.application.package_retention import PruneRetainedPackages
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.model_artifact_store import (
    ArtifactStorageError,
    FilesystemModelArtifactStore,
)


def _version(
    model_version_id: str, version: int, status: ModelLifecycleStatus
) -> ModelVersion:
    return ModelVersion(
        model_version_id=model_version_id,
        version=version,
        dataset_version_id="DSV-000001",
        feature_version="baseline-v1",
        algorithm="linear_regression",
        artifact_uri=f"/data/{model_version_id}",
        trained_at=datetime(2026, 8, 25, tzinfo=UTC),
        training_row_count=10,
        uncertainty_liters=1.0,
        lifecycle_status=status,
    )


class _Models:
    def __init__(self, versions: list[ModelVersion]) -> None:
        self._versions = versions

    def list_all(self) -> list[ModelVersion]:
        return sorted(self._versions, key=lambda v: v.version, reverse=True)

    def get_active(self) -> ModelVersion | None:
        for version in self._versions:
            if version.lifecycle_status is ModelLifecycleStatus.ACTIVE:
                return version
        return None


class _Store:
    def __init__(self, present: set[str]) -> None:
        self.present = set(present)
        self.deleted: list[str] = []

    def exists(self, model_version: str) -> bool:
        return model_version in self.present

    def delete(self, model_version: str) -> None:
        self.deleted.append(model_version)
        self.present.discard(model_version)


def _pruner(versions: list[ModelVersion], keep_retired: int = 3) -> tuple:
    store = _Store({v.model_version_id for v in versions})
    return (
        PruneRetainedPackages(
            models=_Models(versions), store=store, keep_retired=keep_retired
        ),
        store,
    )


def test_the_active_model_is_never_pruned() -> None:
    pruner, store = _pruner([_version("MDL-aktif", 5, ModelLifecycleStatus.ACTIVE)])

    pruner.execute(dry_run=False)

    assert store.deleted == []


def test_candidates_awaiting_review_are_never_pruned() -> None:
    """Deleting one turns a pending review into an entry that can never activate."""
    pruner, store = _pruner(
        [
            _version("MDL-aktif", 5, ModelLifecycleStatus.ACTIVE),
            _version("MDL-kandidat", 6, ModelLifecycleStatus.CANDIDATE),
        ]
    )

    pruner.execute(dry_run=False)

    assert store.deleted == []


def test_the_most_recent_retired_versions_are_kept_as_rollback_targets() -> None:
    versions = [_version("MDL-aktif", 10, ModelLifecycleStatus.ACTIVE)] + [
        _version(f"MDL-lama-{n}", n, ModelLifecycleStatus.RETIRED) for n in range(9, 0, -1)
    ]
    pruner, store = _pruner(versions, keep_retired=3)

    plan = pruner.execute(dry_run=False)

    # The three newest retired versions survive; older ones go.
    assert "MDL-lama-9" in plan.keep
    assert "MDL-lama-8" in plan.keep
    assert "MDL-lama-7" in plan.keep
    assert "MDL-lama-9" not in store.deleted
    assert "MDL-lama-1" in store.deleted
    assert "MDL-aktif" not in store.deleted


def test_nothing_is_deleted_on_a_dry_run() -> None:
    versions = [_version("MDL-aktif", 10, ModelLifecycleStatus.ACTIVE)] + [
        _version(f"MDL-lama-{n}", n, ModelLifecycleStatus.RETIRED) for n in range(9, 0, -1)
    ]
    pruner, store = _pruner(versions)

    plan = pruner.execute(dry_run=True)

    assert plan.prune
    assert store.deleted == []


def test_a_version_with_no_retained_bytes_is_not_listed_for_pruning() -> None:
    """Nothing to delete is not the same as something to delete."""
    versions = [_version("MDL-hilang", 1, ModelLifecycleStatus.RETIRED)]
    store = _Store(set())
    pruner = PruneRetainedPackages(models=_Models(versions), store=store, keep_retired=0)

    plan = pruner.execute(dry_run=False)

    assert plan.prune == ()
    assert store.deleted == []


def test_every_kept_version_carries_the_reason_it_was_kept() -> None:
    """An operator reading the plan has to be able to see why, not just what."""
    versions = [
        _version("MDL-aktif", 3, ModelLifecycleStatus.ACTIVE),
        _version("MDL-kandidat", 4, ModelLifecycleStatus.CANDIDATE),
        _version("MDL-lama", 2, ModelLifecycleStatus.RETIRED),
    ]
    pruner, _ = _pruner(versions)

    plan = pruner.plan()

    assert plan.reasons["MDL-aktif"] == "model aktif"
    assert plan.reasons["MDL-kandidat"] == "kandidat menunggu tinjauan"
    assert plan.reasons["MDL-lama"] == "sasaran rollback"


def test_deleting_really_removes_the_directory(tmp_path: Path) -> None:
    store = FilesystemModelArtifactStore(root=tmp_path)
    store.store("fuel-model-2026.08.25.1", {"manifest.json": b"{}", "model.skops": b"x"})
    assert store.exists("fuel-model-2026.08.25.1")

    store.delete("fuel-model-2026.08.25.1")

    assert not store.exists("fuel-model-2026.08.25.1")


def test_deleting_an_absent_package_is_not_an_error(tmp_path: Path) -> None:
    FilesystemModelArtifactStore(root=tmp_path).delete("fuel-model-2026.08.25.9")


def test_delete_refuses_a_version_that_is_not_a_safe_directory_name(tmp_path: Path) -> None:
    """A recursive delete is the worst place to trust a caller's string."""
    store = FilesystemModelArtifactStore(root=tmp_path / "packages")
    (tmp_path / "penting").mkdir()

    with pytest.raises(ArtifactStorageError):
        store.delete("../penting")

    assert (tmp_path / "penting").is_dir()
