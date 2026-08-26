"""The packager's output must pass the validator (ADR 0009).

This is the test that matters most for the package contract. The packager
and the validator are separate code with separate schemas in between, and
the whole reason the packager lives in this repository is so the two cannot
drift apart. A round-trip is what actually proves that; testing either side
alone would not.
"""

from datetime import UTC, datetime
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
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    REFERENCE_STATISTICS_SCHEMA,
    SMOKE_TESTS_SCHEMA,
    JsonSchemaManifestValidator,
    JsonSchemaValidator,
)
from fuel_predictor.infrastructure.model_artifact_loader import build_loader
from fuel_predictor.infrastructure.zip_model_package_archive import ZipModelPackageArchiveReader
from fuel_predictor.packaging.model_packager import ModelPackageBuilder, PackagingError

_CONTRACT = "numeric-v1"
_RUNTIME = "skops-0.11"


def _model_bytes() -> bytes:
    rows = [[d, h] for d in (10.0, 20.0, 30.0, 40.0) for h in (0.0, 1.0, 2.0)]
    targets = [0.5 * d + 2.0 * h for d, h in rows]
    return bytes(skops_io.dumps(LinearRegression().fit(rows, targets)))


def _builder(**overrides: Any) -> ModelPackageBuilder:
    settings: dict[str, Any] = {
        "model_version": "fuel-model-2026.08.22.1",
        "model_format": "skops",
        "runtime_compatibility_version": _RUNTIME,
        "feature_contract_version": _CONTRACT,
        "feature_schema": [
            {"name": "total_distance_km", "type": "number"},
            {"name": "lifting_hours", "type": "number"},
        ],
        "target_name": "prepared_fuel_liters",
        "target_unit": "liters",
        "training_dataset_version": "DSV-000001",
        "trained_at": datetime(2026, 8, 22, tzinfo=UTC),
        "source_revision": "abc123",
        "metrics": {
            "overall": {
                "mae": 3.0,
                "rmse": 4.0,
                "smape_percent": 12.0,
                "interval_coverage_percent": 90.0,
            }
        },
        "test_set_size": 50,
        "training_row_count": 400,
        "expected_memory_bytes": 10_000_000,
    }
    settings.update(overrides)
    return ModelPackageBuilder(**settings)


def _statistics() -> dict[str, Any]:
    return {
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


def _smoke_tests(expected: float = 17.0) -> dict[str, Any]:
    return {
        "cases": [
            {
                "name": "angkut 30 km dengan 1 jam lifting",
                "features": {"total_distance_km": 30.0, "lifting_hours": 1.0},
                "expected_prediction": expected,
                "tolerance": 0.01,
            }
        ]
    }


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


def _probe() -> ModelVersion:
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


def test_a_packaged_model_validates_without_modification() -> None:
    """The contract's central guarantee: what the packager emits, production accepts."""
    archive = _builder().build(_model_bytes(), _statistics(), _smoke_tests())

    result = _validator().execute(archive, active_metrics=None, probe_version=_probe())

    assert result.manifest.model_version == "fuel-model-2026.08.22.1"
    assert result.eligibility.eligible is True


def test_the_packager_computes_checksums_the_validator_agrees_with() -> None:
    """Checksums are derived from the bytes written, not accepted from a caller."""
    archive = _builder().build(_model_bytes(), _statistics(), _smoke_tests())

    result = _validator().execute(archive, active_metrics=None, probe_version=_probe())

    assert set(result.manifest.package_checksums) == {
        "model.skops",
        "reference-statistics.json",
        "smoke-tests.json",
    }


def test_packaging_is_deterministic_so_a_rebuild_is_byte_identical() -> None:
    """Non-deterministic JSON ordering would change checksums between rebuilds."""
    model = _model_bytes()

    first = _builder().build(model, _statistics(), _smoke_tests())
    second = _builder().build(model, _statistics(), _smoke_tests())

    assert first == second


def test_a_forbidden_format_is_refused_at_packaging_time() -> None:
    with pytest.raises(PackagingError, match="tidak diizinkan"):
        _builder(model_format="pickle").build(_model_bytes(), _statistics(), _smoke_tests())


def test_a_package_without_smoke_tests_is_refused_at_packaging_time() -> None:
    """Caught here rather than in production, so the trainer sees it immediately."""
    with pytest.raises(PackagingError, match="uji asap"):
        _builder().build(_model_bytes(), _statistics(), {"cases": []})


def test_a_smoke_case_missing_a_declared_feature_is_refused() -> None:
    incomplete = {
        "cases": [
            {
                "name": "kurang fitur",
                "features": {"total_distance_km": 30.0},
                "expected_prediction": 17.0,
            }
        ]
    }

    with pytest.raises(PackagingError, match="lifting_hours"):
        _builder().build(_model_bytes(), _statistics(), incomplete)


def test_an_empty_artefact_is_refused() -> None:
    with pytest.raises(PackagingError, match="kosong"):
        _builder().build(b"", _statistics(), _smoke_tests())


def test_a_packaged_model_whose_smoke_case_is_wrong_is_caught_by_the_validator() -> None:
    """The packager cannot know the model is wrong; the validator runs the cases."""
    archive = _builder().build(_model_bytes(), _statistics(), _smoke_tests(expected=999.0))

    from fuel_predictor.domain.model_package import ModelPackageValidationError

    with pytest.raises(ModelPackageValidationError):
        _validator().execute(archive, active_metrics=None, probe_version=_probe())
