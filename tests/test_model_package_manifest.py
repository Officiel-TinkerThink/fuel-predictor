from typing import Any

import pytest

from fuel_predictor.application.model_package_ingestion import ParseModelPackageManifest
from fuel_predictor.domain.model_package import ModelFormat, ModelPackageValidationError
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    JsonSchemaManifestValidator,
)

_FEATURE_CONTRACT_VERSION = "baseline-v1"
_RUNTIME_VERSION = "onnxruntime-1.20"


def _valid_manifest(**overrides: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "model_version": "fuel-model-2026.08.22.1",
        "model_format": "onnx",
        "runtime_compatibility_version": _RUNTIME_VERSION,
        "target": {"name": "prepared_fuel_liters", "unit": "liters"},
        "feature_contract_version": _FEATURE_CONTRACT_VERSION,
        "feature_schema": [
            {"name": "vehicle_category", "type": "string"},
            {"name": "activity_mode", "type": "string"},
            {"name": "distance_source", "type": "string"},
            {"name": "total_distance_km", "type": "number"},
            {"name": "lifting_hours", "type": "number"},
        ],
        "training_dataset_version": "DSV-000001",
        "trained_at": "2026-08-22T00:00:00+00:00",
        "source_revision": "a1b2c3d4",
        "metrics": {
            "overall": {
                "mae": 3.2,
                "rmse": 4.1,
                "smape_percent": 12.5,
                "interval_coverage_percent": 91.0,
            },
            "by_category": [
                {
                    "category": "ANGBER",
                    "mae": 3.2,
                    "rmse": 4.1,
                    "smape_percent": 12.5,
                    "interval_coverage_percent": 91.0,
                }
            ],
        },
        "test_set_size": 120,
        "model_size_bytes": 45_000,
        "expected_memory_bytes": 200_000_000,
        "package_checksums": {
            "model.onnx": "a" * 64,
            "manifest.json": "b" * 64,
            "input-schema.json": "c" * 64,
            "reference-statistics.json": "d" * 64,
            "smoke-tests.json": "e" * 64,
        },
    }
    manifest.update(overrides)
    return manifest


def _parser(**overrides: Any) -> ParseModelPackageManifest:
    defaults: dict[str, Any] = {
        "schema_validator": JsonSchemaManifestValidator(),
        "supported_feature_contract_versions": frozenset({_FEATURE_CONTRACT_VERSION}),
        "supported_runtime_compatibility_versions": frozenset({_RUNTIME_VERSION}),
    }
    defaults.update(overrides)
    return ParseModelPackageManifest(**defaults)


def test_valid_manifest_parses_into_the_domain_shape() -> None:
    manifest = _parser().execute(_valid_manifest())

    assert manifest.model_version == "fuel-model-2026.08.22.1"
    assert manifest.model_format is ModelFormat.ONNX
    assert manifest.feature_names_in_order() == (
        "vehicle_category",
        "activity_mode",
        "distance_source",
        "total_distance_km",
        "lifting_hours",
    )
    assert manifest.overall_metrics.mae == 3.2
    assert manifest.category_metrics[0].category == "ANGBER"
    assert manifest.package_checksums["model.onnx"] == "a" * 64


def test_missing_required_field_is_rejected_with_a_readable_message() -> None:
    manifest = _valid_manifest()
    del manifest["model_version"]

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    assert any("model_version" in message for _field, message in excinfo.value.errors)


@pytest.mark.parametrize("forbidden_format", ["pickle", "joblib", "PICKLE", ""])
def test_pickle_and_joblib_formats_are_rejected_unconditionally(forbidden_format: str) -> None:
    manifest = _valid_manifest(model_format=forbidden_format)

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(manifest)


def test_unrecognized_feature_contract_version_is_rejected() -> None:
    manifest = _valid_manifest(feature_contract_version="some-other-contract-v9")

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    assert any(field == "feature_contract_version" for field, _message in excinfo.value.errors)


def test_unrecognized_runtime_compatibility_version_is_rejected() -> None:
    manifest = _valid_manifest(runtime_compatibility_version="onnxruntime-0.1-ancient")

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    assert any(
        field == "runtime_compatibility_version" for field, _message in excinfo.value.errors
    )


def test_duplicate_feature_names_are_rejected() -> None:
    manifest = _valid_manifest(
        feature_schema=[
            {"name": "total_distance_km", "type": "number"},
            {"name": "total_distance_km", "type": "number"},
        ]
    )

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    assert any(field == "feature_schema" for field, _message in excinfo.value.errors)


def test_missing_checksum_for_a_required_package_member_is_rejected() -> None:
    manifest = _valid_manifest()
    del manifest["package_checksums"]["smoke-tests.json"]

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    assert any(
        field == "package_checksums" and "smoke-tests.json" in message
        for field, message in excinfo.value.errors
    )


def test_multiple_simultaneous_problems_are_all_reported_together() -> None:
    manifest = _valid_manifest(
        feature_contract_version="wrong-contract",
        runtime_compatibility_version="wrong-runtime",
    )
    del manifest["package_checksums"]["smoke-tests.json"]

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(manifest)

    fields = {field for field, _message in excinfo.value.errors}
    assert fields == {
        "feature_contract_version",
        "runtime_compatibility_version",
        "package_checksums",
    }


def test_unknown_top_level_field_is_rejected_by_the_schema() -> None:
    manifest = _valid_manifest()
    manifest["unexpected_extra_field"] = "not part of the contract"

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(manifest)


def test_negative_or_zero_sizes_are_rejected() -> None:
    manifest = _valid_manifest(model_size_bytes=0)

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(manifest)
