"""Registering and activating externally ingested model packages (ADR 0010).

Validation and retention alone leave a package unreachable: without a model
version row there is nothing for activation to target and nothing for rollback
to return to. `RegisterIngestedPackage` closes that gap at upload time, and
`ActivateRetainedModelPackage` is what later promotes one of those candidates.

The ordered activation sequence in `ActivateModelVersion` needs a loader and a
smoke-test runner for the specific candidate being activated, and both are
package-specific. This use case rebuilds them from the retained bytes rather
than reusing anything cached at upload time: activation must prove the bytes
still on disk load and answer correctly *now*, not that they did once.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fuel_predictor.application.model_activation import (
    ActivateModelVersion,
    ActivationRepository,
    ActivationResult,
    ActiveModelHolder,
    LoadedModel,
    MemoryProbe,
)
from fuel_predictor.application.model_package_ingestion import (
    DeterministicSmokeTestRunner,
    ParseModelPackageManifest,
    ParseSmokeTests,
    verify_member_checksums,
)
from fuel_predictor.application.model_package_validation import (
    ArtifactLoaderFactory,
    json_member,
)
from fuel_predictor.domain.model_activation import ModelVersionNotFoundError
from fuel_predictor.domain.model_package import ModelPackageManifest
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


class RetainedPackageStore(Protocol):
    def read_members(self, model_version: str) -> dict[str, bytes]: ...

    def exists(self, model_version: str) -> bool: ...


class RollbackRecorder(Protocol):
    def __call__(
        self, *, target_version_id: str, previous_version_id: str | None, actor: str, reason: str
    ) -> None: ...


class ModelVersionWriter(Protocol):
    def create(self, model: ModelVersion) -> ModelVersion: ...

    def get(self, model_version_id: str) -> ModelVersion | None: ...


@dataclass(frozen=True, slots=True)
class RegisterIngestedPackage:
    """Record a validated package as a candidate model version.

    Keyed by the manifest's own `model_version`, which is also the directory
    the artefact store retains it under — so "the row exists" and "the bytes
    exist" cannot drift apart into a candidate nothing can load.
    """

    models: ModelVersionWriter

    def execute(self, manifest: ModelPackageManifest, artifact_uri: str) -> ModelVersion:
        existing = self.models.get(manifest.model_version)
        if existing is not None:
            # Re-uploading the same version is not an error: validation already
            # proved these bytes, and the retained copy has been refreshed.
            return existing
        return self.models.create(
            ModelVersion(
                model_version_id=manifest.model_version,
                version=0,
                dataset_version_id=manifest.training_dataset_version,
                feature_version=manifest.feature_contract_version,
                algorithm=f"paket-eksternal ({manifest.model_format.value})",
                artifact_uri=artifact_uri,
                trained_at=manifest.trained_at,
                # The package contract carries a *test* set size, not a training
                # row count. Recording the test size here would quietly mislabel
                # it, so this stays 0 until the manifest carries the real figure.
                training_row_count=0,
                # Mean absolute error is the package's own summary of how far it
                # typically lands from the truth, which is the right basis for
                # the interval shown alongside a prediction.
                uncertainty_liters=manifest.overall_metrics.mae,
                lifecycle_status=ModelLifecycleStatus.CANDIDATE,
            )
        )


class ModelVersionReader(Protocol):
    def get(self, model_version_id: str) -> ModelVersion | None: ...

    def get_active(self) -> ModelVersion | None: ...


@dataclass(frozen=True, slots=True)
class ActivateRetainedModelPackage:
    store: RetainedPackageStore
    models: ModelVersionReader
    parse_manifest: ParseModelPackageManifest
    parse_smoke_tests: ParseSmokeTests
    build_artifact_loader: ArtifactLoaderFactory
    holder: ActiveModelHolder
    repository: ActivationRepository
    memory_probe: MemoryProbe
    health_check: Callable[[LoadedModel], str | None]
    record_rollback: "RollbackRecorder"
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def can_activate(self, model_version_id: str) -> bool:
        """Whether this version has retained bytes to activate from.

        Models trained in-process have no package, so the caller needs to know
        which activation path applies before offering one.
        """
        return self.store.exists(model_version_id)

    def inspect(self, model_version_id: str) -> dict[str, object]:
        """Answer "would this activate cleanly?" without changing anything.

        Runs the same checks activation runs up to the point of loading: the
        version exists, its bytes are retained, and those bytes still match the
        manifest they were accepted under.
        """
        candidate = self.models.get(model_version_id)
        if candidate is None:
            return {"model_version_id": model_version_id, "activatable": False,
                    "reason": "Versi model tidak ditemukan."}
        if not self.store.exists(model_version_id):
            return {"model_version_id": model_version_id, "activatable": False,
                    "reason": "Berkas paket untuk versi ini tidak tersimpan."}
        try:
            members = self.store.read_members(model_version_id)
            manifest = self.parse_manifest.execute(json_member(members, "manifest.json"))
            verify_member_checksums(members, manifest.package_checksums)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return {"model_version_id": model_version_id, "activatable": False,
                    "reason": f"{type(error).__name__}: {error}"}
        return {
            "model_version_id": model_version_id,
            "activatable": True,
            "lifecycle_status": candidate.lifecycle_status.value,
            "expected_memory_bytes": manifest.expected_memory_bytes,
            "trained_at": manifest.trained_at.isoformat(),
        }

    def rollback(
        self,
        target_version_id: str,
        expected_active_version_id: str | None,
        actor: str,
        reason: str,
    ) -> ActivationResult:
        """Return to a retained known-good version (ADR 0010).

        Not `RollbackModelVersion`, which takes a prebuilt `ActivateModelVersion`
        as a collaborator. For a package the loader and smoke-test runner are
        package-specific and must be rebuilt from the retained bytes, which is
        exactly what this class does — so the audit-before-attempt rule is
        applied here over the same sequence rather than duplicating the rebuild
        into that class.
        """
        if not reason.strip():
            raise ValueError("Alasan rollback wajib diisi.")
        # Recorded before the attempt: an operator's decision to roll back is
        # worth keeping even when the attempt then loses a concurrency race,
        # because that is exactly the situation someone reconstructs later.
        self.record_rollback(
            target_version_id=target_version_id,
            previous_version_id=expected_active_version_id,
            actor=actor,
            reason=reason.strip(),
        )
        return self.execute(target_version_id)

    def execute(self, model_version_id: str) -> ActivationResult:
        candidate = self.models.get(model_version_id)
        if candidate is None:
            raise ModelVersionNotFoundError(model_version_id)

        members = self.store.read_members(model_version_id)
        manifest = self.parse_manifest.execute(json_member(members, "manifest.json"))

        # The bytes have been sitting on disk since upload. Re-verifying them
        # against the manifest is the difference between "these bytes were
        # trustworthy once" and "these bytes are what we are about to load".
        verify_member_checksums(members, manifest.package_checksums)

        cases = self.parse_smoke_tests.execute(json_member(members, "smoke-tests.json"))

        active = self.models.get_active()
        sequence = ActivateModelVersion(
            holder=self.holder,
            loader=self.build_artifact_loader(manifest, members),
            smoke_tests=DeterministicSmokeTestRunner(cases=cases),
            repository=self.repository,
            memory_probe=self.memory_probe,
            health_check=self.health_check,
            now=self.now,
        )
        # The manifest's own declared footprint is what the capacity check
        # guards against; a package that understates it fails on load, which
        # is the failure the sequence already leaves the previous model
        # serving through.
        return sequence.execute(
            candidate=candidate,
            expected_active_version_id=active.model_version_id if active else None,
            required_memory_bytes=manifest.expected_memory_bytes,
        )
