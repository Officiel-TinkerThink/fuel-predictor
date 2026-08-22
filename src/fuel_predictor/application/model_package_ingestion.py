"""Manifest validation for uploaded model packages (ADR 0009).

This is validation steps 4-5 of the plan's numbered list ("validate the
manifest and input schema" / "confirm feature-contract and runtime
compatibility"). Steps 1-3 (archive/size limits, path generation, checksum
and signature verification) belong to the archive-handling layer that opens
the ZIP, which does not exist yet — see
docs/production/implementation-progress.md for what's next. Steps 6-9
(isolated load, smoke tests, comparison, persist+audit) come after that.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
from typing import Any, Protocol

from fuel_predictor.domain.model_package import (
    CategoricalFeatureSummary,
    FeatureSchemaEntry,
    FeatureSummary,
    ManifestCategoryMetrics,
    ManifestMetrics,
    ModelFormat,
    ModelPackageManifest,
    ModelPackageValidationError,
    NumericFeatureSummary,
    ReferenceStatistics,
    SmokeTestCase,
    TargetDefinition,
)


@dataclass(frozen=True, slots=True)
class ModelPackageArchiveLimits:
    """Bounds an uploaded archive must respect before anything inside it is trusted.

    Every one of these exists to stop a specific attack: an oversized upload
    exhausting disk, a decompression bomb exhausting memory, or a
    many-tiny-members archive exhausting time.
    """

    max_archive_bytes: int
    max_extracted_bytes: int
    max_member_count: int
    max_compression_ratio: int


class ModelPackageArchiveReader(Protocol):
    """Safely turns archive bytes into named members held in memory.

    Implementations must enforce `ModelPackageArchiveLimits` and reject any
    member whose name is absolute or escapes the package root, raising
    `ModelPackageValidationError`. Production generates its own storage paths
    from the validated model version (ADR 0009) and never uses these names as
    filesystem paths, but a hostile name is still evidence of a hostile
    package and is refused outright.
    """

    def read_members(self, archive_bytes: bytes) -> Mapping[str, bytes]: ...


def verify_member_checksums(
    members: Mapping[str, bytes], declared_checksums: Mapping[str, str]
) -> None:
    """Confirm the archive's contents are exactly what the manifest declares.

    `manifest.json` itself is excluded: it cannot meaningfully carry a
    checksum of the bytes that contain that very checksum. Everything else
    must match, with no unexplained extras in either direction.
    """
    errors: list[tuple[str, str]] = []
    verifiable = {name: payload for name, payload in members.items() if name != "manifest.json"}
    declared = {
        name: digest
        for name, digest in declared_checksums.items()
        if name != "manifest.json"
    }

    for name in sorted(set(verifiable) - set(declared)):
        errors.append(
            ("package_checksums", f"Berkas '{name}' ada dalam arsip tetapi tidak dalam manifest.")
        )
    for name in sorted(set(declared) - set(verifiable)):
        errors.append(
            ("package_checksums", f"Berkas '{name}' disebut manifest tetapi tidak ada dalam arsip.")
        )
    for name in sorted(set(verifiable) & set(declared)):
        actual = sha256(verifiable[name]).hexdigest()
        if not compare_digest(actual, declared[name]):
            errors.append(("package_checksums", f"Checksum berkas '{name}' tidak cocok."))

    if errors:
        raise ModelPackageValidationError(errors)


class ManifestSchemaValidator(Protocol):
    """Checks a raw manifest against the published JSON Schema.

    Returns human-readable error messages; an empty sequence means the
    manifest matches the schema's shape. Business rules beyond shape
    (feature-contract compatibility, checksum completeness) are this
    module's job, not the schema validator's.
    """

    def validate(self, raw_manifest: Mapping[str, Any]) -> Sequence[str]: ...


# `input-schema.json` and `checksum.sha256` appeared in the production plan's
# original illustrative file list and were dropped during implementation: each
# duplicated a field the manifest already carries authoritatively (the ordered
# feature schema, and every member's checksum). See the amendment note in
# docs/production/self-service-production-plan.md.
# `manifest.json` is deliberately absent: it cannot carry a checksum of the
# bytes that contain that very checksum, which is also why
# `verify_member_checksums` excludes it. Requiring one here while excluding it
# there made a well-formed package impossible to build — caught by the
# end-to-end flow test, not by either unit test on its own.
_REQUIRED_PACKAGE_MEMBERS = frozenset({"reference-statistics.json", "smoke-tests.json"})


@dataclass(frozen=True, slots=True)
class ParseModelPackageManifest:
    """Validate a raw uploaded manifest and produce the typed domain shape.

    Raises ModelPackageValidationError with every failure found, not just
    the first one.
    """

    schema_validator: ManifestSchemaValidator
    supported_feature_contract_versions: frozenset[str]
    supported_runtime_compatibility_versions: frozenset[str]

    def execute(self, raw_manifest: Mapping[str, Any]) -> ModelPackageManifest:
        schema_errors = self.schema_validator.validate(raw_manifest)
        if schema_errors:
            raise ModelPackageValidationError([("manifest", message) for message in schema_errors])

        errors = list(self._business_rule_errors(raw_manifest))
        if errors:
            raise ModelPackageValidationError(errors)

        return _build_manifest(raw_manifest)

    def _business_rule_errors(
        self, raw_manifest: Mapping[str, Any]
    ) -> list[tuple[str, str]]:
        errors: list[tuple[str, str]] = []

        feature_contract_version = raw_manifest["feature_contract_version"]
        if feature_contract_version not in self.supported_feature_contract_versions:
            errors.append(
                (
                    "feature_contract_version",
                    f"Versi kontrak fitur '{feature_contract_version}' tidak dikenali produksi.",
                )
            )

        runtime_version = raw_manifest["runtime_compatibility_version"]
        if runtime_version not in self.supported_runtime_compatibility_versions:
            errors.append(
                (
                    "runtime_compatibility_version",
                    f"Versi kompatibilitas runtime '{runtime_version}' tidak didukung produksi.",
                )
            )

        feature_names = [entry["name"] for entry in raw_manifest["feature_schema"]]
        if len(feature_names) != len(set(feature_names)):
            errors.append(("feature_schema", "Nama fitur tidak boleh berulang."))

        checksums = raw_manifest["package_checksums"]
        missing_checksums = _REQUIRED_PACKAGE_MEMBERS - checksums.keys()
        if missing_checksums:
            errors.append(
                (
                    "package_checksums",
                    "Checksum belum tersedia untuk: " + ", ".join(sorted(missing_checksums)),
                )
            )

        return errors


@dataclass(frozen=True, slots=True)
class ParseSmokeTests:
    """Validate and load a package's `smoke-tests.json`."""

    schema_validator: ManifestSchemaValidator

    def execute(self, raw: Mapping[str, Any]) -> tuple[SmokeTestCase, ...]:
        errors = self.schema_validator.validate(raw)
        if errors:
            raise ModelPackageValidationError(
                [("smoke-tests.json", message) for message in errors]
            )
        return tuple(
            SmokeTestCase(
                name=case["name"],
                features=dict(case["features"]),
                expected_prediction=case["expected_prediction"],
                tolerance=case.get("tolerance", 0.01),
            )
            for case in raw["cases"]
        )


@dataclass(frozen=True, slots=True)
class ParseReferenceStatistics:
    """Validate and load a package's `reference-statistics.json`.

    Also checks the summary against the manifest's feature schema: a baseline
    that describes different features than the model consumes cannot produce a
    meaningful drift verdict, and silently computing one anyway would be worse
    than refusing.
    """

    schema_validator: ManifestSchemaValidator

    def execute(
        self, raw: Mapping[str, Any], manifest: ModelPackageManifest
    ) -> ReferenceStatistics:
        errors = [
            ("reference-statistics.json", message)
            for message in self.schema_validator.validate(raw)
        ]
        if errors:
            raise ModelPackageValidationError(errors)

        declared = set(manifest.feature_names_in_order())
        summarised = set(raw["features"])
        for name in sorted(declared - summarised):
            errors.append(
                ("reference-statistics.json", f"Fitur '{name}' tidak memiliki statistik referensi.")
            )
        for name in sorted(summarised - declared):
            errors.append(
                (
                    "reference-statistics.json",
                    f"Statistik referensi memuat fitur '{name}' yang tidak ada dalam manifest.",
                )
            )
        if errors:
            raise ModelPackageValidationError(errors)

        return ReferenceStatistics(
            row_count=raw["row_count"],
            features={
                name: _feature_summary(summary) for name, summary in raw["features"].items()
            },
        )


def _feature_summary(raw: Mapping[str, Any]) -> FeatureSummary:
    if raw["kind"] == "numeric":
        return NumericFeatureSummary(
            minimum=raw["minimum"],
            maximum=raw["maximum"],
            mean=raw["mean"],
            standard_deviation=raw["standard_deviation"],
            quantiles=dict(raw.get("quantiles", {})),
        )
    return CategoricalFeatureSummary(frequencies=dict(raw["frequencies"]))


@dataclass(frozen=True, slots=True)
class DeterministicSmokeTestRunner:
    """Replays a package's own declared cases against the loaded candidate.

    Every case runs even after one fails, so the operator sees the full
    picture in one pass instead of fixing and re-uploading repeatedly. A case
    that raises is a failure too, not a crash: a model that errors on a case
    it declared it could answer is exactly what this step exists to catch.
    """

    cases: tuple[SmokeTestCase, ...]

    def run(self, loaded: Any) -> list[str]:
        failures: list[str] = []
        for case in self.cases:
            try:
                actual = loaded.predict(case.features)
            except Exception as error:  # noqa: BLE001 - a raising case is a failure
                failures.append(f"{case.name}: model gagal memproses kasus ({error})")
                continue
            failure = case.failure_against(float(actual))
            if failure is not None:
                failures.append(failure)
        return failures


def _build_manifest(raw: Mapping[str, Any]) -> ModelPackageManifest:
    overall = raw["metrics"]["overall"]
    category_entries = raw["metrics"].get("by_category", [])
    return ModelPackageManifest(
        model_version=raw["model_version"],
        model_format=ModelFormat(raw["model_format"]),
        runtime_compatibility_version=raw["runtime_compatibility_version"],
        target=TargetDefinition(name=raw["target"]["name"], unit=raw["target"]["unit"]),
        feature_contract_version=raw["feature_contract_version"],
        feature_schema=tuple(
            FeatureSchemaEntry(name=entry["name"], type=entry["type"])
            for entry in raw["feature_schema"]
        ),
        training_dataset_version=raw["training_dataset_version"],
        trained_at=datetime.fromisoformat(raw["trained_at"]),
        source_revision=raw["source_revision"],
        overall_metrics=_metrics(overall),
        category_metrics=tuple(
            ManifestCategoryMetrics(category=entry["category"], metrics=_metrics(entry))
            for entry in category_entries
        ),
        test_set_size=raw["test_set_size"],
        model_size_bytes=raw["model_size_bytes"],
        expected_memory_bytes=raw["expected_memory_bytes"],
        package_checksums=dict(raw["package_checksums"]),
    )


def _metrics(raw: Mapping[str, Any]) -> ManifestMetrics:
    return ManifestMetrics(
        mae=raw["mae"],
        rmse=raw["rmse"],
        smape_percent=raw["smape_percent"],
        interval_coverage_percent=raw["interval_coverage_percent"],
    )
