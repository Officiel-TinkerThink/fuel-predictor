"""End-to-end package validation (production plan steps 1-9).

Builds a real ZIP containing a genuinely trained model and runs the whole
flow, so this covers the wiring between pieces that their individual unit
tests cannot: correct ordering, and each step actually receiving what the
previous one produced.
"""

import json
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Any

import pytest
import skops.io as skops_io
from sklearn.linear_model import LinearRegression

from fuel_predictor.application.model_package_ingestion import (
    ModelPackageArchiveLimits,
    ParseModelPackageManifest,
    ParseReferenceStatistics,
    ParseSmokeTests,
)
from fuel_predictor.application.model_package_validation import ValidateModelPackage
from fuel_predictor.application.model_promotion_policy import (
    EvaluateCandidateAgainstPolicy,
    PromotionPolicy,
)
from fuel_predictor.domain.model_package import ManifestMetrics, ModelPackageValidationError
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    REFERENCE_STATISTICS_SCHEMA,
    SMOKE_TESTS_SCHEMA,
    JsonSchemaManifestValidator,
    JsonSchemaValidator,
)
from fuel_predictor.infrastructure.model_artifact_loader import build_loader
from fuel_predictor.infrastructure.zip_model_package_archive import ZipModelPackageArchiveReader

_CONTRACT = "numeric-v1"
_RUNTIME = "skops-0.11"


def _model_bytes() -> bytes:
    """fuel = 0.5 * distance + 2 * lifting_hours, fitted exactly."""
    rows = [[d, h] for d in (10.0, 20.0, 30.0, 40.0) for h in (0.0, 1.0, 2.0)]
    targets = [0.5 * d + 2.0 * h for d, h in rows]
    return bytes(skops_io.dumps(LinearRegression().fit(rows, targets)))


def _package(
    *,
    model_payload: bytes | None = None,
    corrupt_checksum: bool = False,
    smoke_expectation: float = 17.0,
    test_set_size: int = 50,
    mae: float = 3.0,
) -> bytes:
    model = model_payload if model_payload is not None else _model_bytes()
    statistics = {
        "row_count": 120,
        "features": {
            "total_distance_km": {
                "kind": "numeric",
                "minimum": 10.0,
                "maximum": 40.0,
                "mean": 25.0,
                "standard_deviation": 11.0,
            },
            "lifting_hours": {
                "kind": "numeric",
                "minimum": 0.0,
                "maximum": 2.0,
                "mean": 1.0,
                "standard_deviation": 0.8,
            },
        },
    }
    smoke = {
        "cases": [
            {
                "name": "angkut 30 km dengan 1 jam lifting",
                "features": {"total_distance_km": 30.0, "lifting_hours": 1.0},
                "expected_prediction": smoke_expectation,
                "tolerance": 0.01,
            }
        ]
    }
    statistics_bytes = json.dumps(statistics).encode()
    smoke_bytes = json.dumps(smoke).encode()

    manifest = {
        "model_version": "fuel-model-2026.08.22.1",
        "model_format": "skops",
        "runtime_compatibility_version": _RUNTIME,
        "target": {"name": "prepared_fuel_liters", "unit": "liters"},
        "feature_contract_version": _CONTRACT,
        "feature_schema": [
            {"name": "total_distance_km", "type": "number"},
            {"name": "lifting_hours", "type": "number"},
        ],
        "training_dataset_version": "DSV-000001",
        "trained_at": "2026-08-22T00:00:00+00:00",
        "source_revision": "abc123",
        "metrics": {
            "overall": {
                "mae": mae,
                "rmse": 4.0,
                "smape_percent": 12.0,
                "interval_coverage_percent": 90.0,
            }
        },
        "test_set_size": test_set_size,
        "model_size_bytes": len(model),
        "expected_memory_bytes": 10_000_000,
        "package_checksums": {
            "model.skops": "0" * 64 if corrupt_checksum else sha256(model).hexdigest(),
            "reference-statistics.json": sha256(statistics_bytes).hexdigest(),
            "smoke-tests.json": sha256(smoke_bytes).hexdigest(),
        },
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("model.skops", model)
        archive.writestr("reference-statistics.json", statistics_bytes)
        archive.writestr("smoke-tests.json", smoke_bytes)
    return buffer.getvalue()


def _probe_version() -> ModelVersion:
    return ModelVersion(
        model_version_id="MDL-PROBE",
        version=0,
        dataset_version_id="DSV-000001",
        feature_version=_CONTRACT,
        algorithm="linear_regression",
        artifact_uri="memory://probe",
        trained_at=datetime(2026, 8, 22, tzinfo=UTC),
        training_row_count=12,
        uncertainty_liters=2.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )


def _validator() -> ValidateModelPackage:
    def loader_factory(manifest: Any, members: Any) -> Any:
        payload = members["model.skops"]
        return build_loader(
            manifest, members, trusted_skops_types=skops_io.get_untrusted_types(data=payload)
        )

    return ValidateModelPackage(
        archive_reader=ZipModelPackageArchiveReader(
            ModelPackageArchiveLimits(
                max_archive_bytes=10_000_000,
                max_extracted_bytes=40_000_000,
                max_member_count=16,
                max_compression_ratio=200,
            )
        ),
        parse_manifest=ParseModelPackageManifest(
            schema_validator=JsonSchemaManifestValidator(),
            supported_feature_contract_versions=frozenset({_CONTRACT}),
            supported_runtime_compatibility_versions=frozenset({_RUNTIME}),
        ),
        parse_reference_statistics=ParseReferenceStatistics(
            schema_validator=JsonSchemaValidator(REFERENCE_STATISTICS_SCHEMA)
        ),
        parse_smoke_tests=ParseSmokeTests(
            schema_validator=JsonSchemaValidator(SMOKE_TESTS_SCHEMA)
        ),
        evaluate_policy=EvaluateCandidateAgainstPolicy(
            policy=PromotionPolicy(max_mae_liters=5.0, max_mae_regression_ratio=1.1)
        ),
        build_artifact_loader=loader_factory,
    )


def test_a_well_formed_package_validates_all_the_way_through() -> None:
    result = _validator().execute(
        _package(),
        active_metrics=ManifestMetrics(4.0, 5.0, 15.0, 88.0),
        probe_version=_probe_version(),
    )

    assert result.manifest.model_version == "fuel-model-2026.08.22.1"
    assert result.reference_statistics.row_count == 120
    assert len(result.smoke_tests) == 1
    assert result.eligibility.eligible is True


def test_a_tampered_artefact_is_caught_before_it_is_ever_loaded() -> None:
    """Checksum verification must precede loading, not follow it.

    If these ran the other way round, production would execute unverified
    bytes and only afterwards notice they were not what the manifest
    described — the exact risk ADR 0009 restricts formats to avoid.
    """
    with pytest.raises(ModelPackageValidationError) as excinfo:
        _validator().execute(
            _package(corrupt_checksum=True), active_metrics=None, probe_version=_probe_version()
        )

    assert any(field == "package_checksums" for field, _ in excinfo.value.errors)


def test_a_model_failing_its_own_smoke_tests_is_rejected() -> None:
    with pytest.raises(ModelPackageValidationError) as excinfo:
        _validator().execute(
            _package(smoke_expectation=999.0), active_metrics=None, probe_version=_probe_version()
        )

    assert any(field == "smoke-tests" for field, _ in excinfo.value.errors)


def test_an_ineligible_candidate_still_validates_but_is_not_eligible() -> None:
    """Failing policy is a verdict, not a validation error.

    An operator needs to see the comparison for a candidate that is merely
    worse; only a package that is malformed or dishonest is refused outright.
    """
    result = _validator().execute(
        _package(test_set_size=2), active_metrics=None, probe_version=_probe_version()
    )

    assert result.eligibility.eligible is False
    assert any("set uji" in reason for reason in result.eligibility.reasons)


def test_a_package_missing_a_required_member_is_rejected() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")

    with pytest.raises(ModelPackageValidationError):
        _validator().execute(
            buffer.getvalue(), active_metrics=None, probe_version=_probe_version()
        )


def test_a_member_that_is_not_valid_json_is_rejected_readably() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{ this is not json")

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _validator().execute(
            buffer.getvalue(), active_metrics=None, probe_version=_probe_version()
        )

    assert any("JSON" in message for _field, message in excinfo.value.errors)
