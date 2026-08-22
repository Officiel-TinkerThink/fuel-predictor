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
from typing import Any, Protocol

from fuel_predictor.domain.model_package import (
    FeatureSchemaEntry,
    ManifestCategoryMetrics,
    ManifestMetrics,
    ModelFormat,
    ModelPackageManifest,
    ModelPackageValidationError,
    TargetDefinition,
)


class ManifestSchemaValidator(Protocol):
    """Checks a raw manifest against the published JSON Schema.

    Returns human-readable error messages; an empty sequence means the
    manifest matches the schema's shape. Business rules beyond shape
    (feature-contract compatibility, checksum completeness) are this
    module's job, not the schema validator's.
    """

    def validate(self, raw_manifest: Mapping[str, Any]) -> Sequence[str]: ...


_REQUIRED_PACKAGE_MEMBERS = frozenset(
    {"manifest.json", "input-schema.json", "reference-statistics.json", "smoke-tests.json"}
)


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
