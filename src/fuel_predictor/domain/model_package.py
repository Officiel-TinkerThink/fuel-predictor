"""External model package manifest (ADR 0009).

Production never trains here; it only accepts a package produced by the
external training environment's packager and validates it before a candidate
can be loaded. This module is the validated, in-memory shape of that
package's manifest.json — see schemas/model-package/manifest.schema.json for
the published contract both the packager and this validation target.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ModelFormat(StrEnum):
    ONNX = "onnx"
    SKOPS = "skops"


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    name: str
    unit: str


@dataclass(frozen=True, slots=True)
class FeatureSchemaEntry:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class ManifestMetrics:
    mae: float
    rmse: float
    smape_percent: float
    interval_coverage_percent: float


@dataclass(frozen=True, slots=True)
class ManifestCategoryMetrics:
    category: str
    metrics: ManifestMetrics


@dataclass(frozen=True, slots=True)
class ModelPackageManifest:
    model_version: str
    model_format: ModelFormat
    runtime_compatibility_version: str
    target: TargetDefinition
    feature_contract_version: str
    feature_schema: tuple[FeatureSchemaEntry, ...]
    training_dataset_version: str
    trained_at: datetime
    source_revision: str
    overall_metrics: ManifestMetrics
    category_metrics: tuple[ManifestCategoryMetrics, ...]
    test_set_size: int
    model_size_bytes: int
    expected_memory_bytes: int
    package_checksums: dict[str, str]

    def feature_names_in_order(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.feature_schema)


@dataclass(frozen=True, slots=True)
class SmokeTestCase:
    """One deterministic case a package asserts about its own model.

    `tolerance` is absolute and defaults to a small non-zero value: floating
    point differs across platforms and runtime versions, so demanding exact
    equality would fail packages for reasons unrelated to model correctness.
    """

    name: str
    features: dict[str, str | float | bool]
    expected_prediction: float
    tolerance: float = 0.01

    def failure_against(self, actual: float) -> str | None:
        """Describe the mismatch, or None when the model answered acceptably."""
        deviation = abs(actual - self.expected_prediction)
        if deviation <= self.tolerance:
            return None
        return (
            f"{self.name}: diharapkan {self.expected_prediction:g} "
            f"(toleransi {self.tolerance:g}), diperoleh {actual:g}"
        )


class ModelPackageValidationError(ValueError):
    """One or more fields of an uploaded package failed validation.

    Every failure is collected before raising, so an operator or agent can
    fix a whole package in one pass instead of one error at a time.
    """

    def __init__(self, errors: Sequence[tuple[str, str]]) -> None:
        if not errors:
            raise ValueError("ModelPackageValidationError requires at least one error.")
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors))
        self.errors = tuple(errors)
