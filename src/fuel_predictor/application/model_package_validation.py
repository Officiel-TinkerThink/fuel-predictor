"""The full package validation flow (production plan steps 1-9).

Everything this orchestrates already exists and is tested on its own; the
value here is running the steps *in the plan's order*, because the order is
itself a safety property. Cheap structural checks run before anything is
parsed, parsing runs before anything is loaded, and the model is only ever
loaded after its bytes have been checksum-verified against a manifest that
already passed validation. A flow that loaded first and validated afterwards
would execute an unverified artefact, which is exactly what ADR 0009 exists
to prevent.

Validation never activates anything. It produces a verdict; promotion stays
a manual act (ADR 0004).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fuel_predictor.application.model_package_ingestion import (
    DeterministicSmokeTestRunner,
    ModelPackageArchiveReader,
    ParseModelPackageManifest,
    ParseReferenceStatistics,
    ParseSmokeTests,
    verify_member_checksums,
)
from fuel_predictor.application.model_promotion_policy import (
    EvaluateCandidateAgainstPolicy,
    PromotionEligibility,
)
from fuel_predictor.domain.model_package import (
    ManifestMetrics,
    ModelPackageManifest,
    ModelPackageValidationError,
    ReferenceStatistics,
    SmokeTestCase,
)


class ArtifactLoaderFactory(Protocol):
    """Builds a loader for the already-verified members of one package."""

    def __call__(
        self, manifest: ModelPackageManifest, members: Mapping[str, bytes]
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class ValidatedModelPackage:
    manifest: ModelPackageManifest
    reference_statistics: ReferenceStatistics
    smoke_tests: tuple[SmokeTestCase, ...]
    eligibility: PromotionEligibility
    members: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class ValidateModelPackage:
    archive_reader: ModelPackageArchiveReader
    parse_manifest: ParseModelPackageManifest
    parse_reference_statistics: ParseReferenceStatistics
    parse_smoke_tests: ParseSmokeTests
    evaluate_policy: EvaluateCandidateAgainstPolicy
    build_artifact_loader: ArtifactLoaderFactory

    def execute(
        self,
        archive_bytes: bytes,
        active_metrics: ManifestMetrics | None,
        probe_version: Any,
    ) -> ValidatedModelPackage:
        # Steps 1-2: bounded, traversal-safe extraction.
        members = self.archive_reader.read_members(archive_bytes)

        manifest = self.parse_manifest.execute(_json_member(members, "manifest.json"))

        # Step 3, and it must come before the artefact is touched: the bytes
        # about to be loaded are only trustworthy once they match a manifest
        # that has itself been validated.
        verify_member_checksums(members, manifest.package_checksums)

        statistics = self.parse_reference_statistics.execute(
            _json_member(members, "reference-statistics.json"), manifest
        )
        cases = self.parse_smoke_tests.execute(_json_member(members, "smoke-tests.json"))

        # Steps 6-7: load in isolation, then replay the package's own cases.
        loader = self.build_artifact_loader(manifest, members)
        loaded = loader.load(probe_version)
        failures = DeterministicSmokeTestRunner(cases=cases).run(loaded)
        if failures:
            raise ModelPackageValidationError(
                [("smoke-tests", failure) for failure in failures]
            )

        # Step 8: eligibility only. Nothing here promotes anything.
        eligibility = self.evaluate_policy.execute(manifest, active_metrics)

        return ValidatedModelPackage(
            manifest=manifest,
            reference_statistics=statistics,
            smoke_tests=cases,
            eligibility=eligibility,
            members=members,
        )


def _json_member(members: Mapping[str, bytes], name: str) -> Mapping[str, Any]:
    if name not in members:
        raise ModelPackageValidationError([("archive", f"Paket tidak memuat '{name}'.")])
    try:
        parsed = json.loads(members[name].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelPackageValidationError(
            [(name, f"Berkas bukan JSON yang valid: {error}")]
        ) from error
    if not isinstance(parsed, dict):
        raise ModelPackageValidationError([(name, "Isi berkas harus berupa objek JSON.")])
    return parsed


def required_members() -> Sequence[str]:
    return ("manifest.json", "reference-statistics.json", "smoke-tests.json")
