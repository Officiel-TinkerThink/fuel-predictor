"""Pruning retained model packages without destroying a rollback target.

Retention here is a correctness concern, not disk hygiene (ADR 0010). Rollback
can only return to a version whose bytes still exist, so a prune that frees
space by deleting the version an operator would fall back to has not tidied the
disk — it has removed the recovery path, and nobody finds out until the day
they need it.

The rule is therefore stated as what is *kept*, never as what is deleted:
anything not positively identified as keepable is left alone. A prune that
errs toward keeping wastes disk; one that errs toward deleting loses the
ability to recover.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


class RetainedPackagePruner(Protocol):
    def exists(self, model_version: str) -> bool: ...

    def delete(self, model_version: str) -> None: ...


class ModelVersionLister(Protocol):
    def list_all(self) -> Sequence[ModelVersion]: ...

    def get_active(self) -> ModelVersion | None: ...


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    keep: tuple[str, ...]
    prune: tuple[str, ...]
    reasons: dict[str, str]


@dataclass(frozen=True, slots=True)
class PruneRetainedPackages:
    models: ModelVersionLister
    store: RetainedPackagePruner
    keep_retired: int = 3

    def plan(self) -> RetentionPlan:
        """Decide what to keep. Deliberately separate from doing it.

        An operator can read the plan before anything is deleted, and the
        decision is testable without a filesystem.
        """
        versions = list(self.models.list_all())
        active = self.models.get_active()
        keep: dict[str, str] = {}

        if active is not None:
            keep[active.model_version_id] = "model aktif"

        # Candidates are awaiting a human decision. Deleting one turns a
        # pending review into a mystery entry that can never be activated.
        for version in versions:
            if version.lifecycle_status is ModelLifecycleStatus.CANDIDATE:
                keep[version.model_version_id] = "kandidat menunggu tinjauan"

        # The most recent retired versions are the rollback targets. This is
        # the whole reason the job exists in this shape.
        retired = [
            version
            for version in versions
            if version.lifecycle_status is ModelLifecycleStatus.RETIRED
        ]
        for version in retired[: self.keep_retired]:
            keep.setdefault(version.model_version_id, "sasaran rollback")

        prune = tuple(
            version.model_version_id
            for version in versions
            if version.model_version_id not in keep
            and self.store.exists(version.model_version_id)
        )
        return RetentionPlan(keep=tuple(keep), prune=prune, reasons=keep)

    def execute(self, dry_run: bool = True) -> RetentionPlan:
        plan = self.plan()
        if dry_run:
            return plan
        for model_version in plan.prune:
            self.store.delete(model_version)
        return plan
