"""Shared builders for model-package test data.

Lives here rather than in one of the test modules so the package tests do not
import from each other: a helper reached across test files couples them, and
editing one test's fixture to suit itself would silently change another's
meaning.
"""

from typing import Any

FEATURE_CONTRACT_VERSION = "baseline-v1"
RUNTIME_VERSION = "onnxruntime-1.20"


def valid_manifest(**overrides: Any) -> dict[str, Any]:
    """A manifest that passes every schema and business rule, for tests to spoil."""
    manifest: dict[str, Any] = {
        "model_version": "fuel-model-2026.08.22.1",
        "model_format": "onnx",
        "runtime_compatibility_version": RUNTIME_VERSION,
        "target": {"name": "prepared_fuel_liters", "unit": "liters"},
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
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
            "reference-statistics.json": "d" * 64,
            "smoke-tests.json": "e" * 64,
        },
    }
    manifest.update(overrides)
    return manifest


def valid_reference_statistics(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "row_count": 120,
        "features": {
            "vehicle_category": {"kind": "categorical", "frequencies": {"ANGBER": 1.0}},
            "activity_mode": {
                "kind": "categorical",
                "frequencies": {"transport": 0.7, "lifting": 0.3},
            },
            "distance_source": {"kind": "categorical", "frequencies": {"manual": 1.0}},
            "total_distance_km": {
                "kind": "numeric",
                "minimum": 5.0,
                "maximum": 90.0,
                "mean": 32.4,
                "standard_deviation": 18.1,
                "quantiles": {"0.5": 30.0},
            },
            "lifting_hours": {
                "kind": "numeric",
                "minimum": 0.0,
                "maximum": 6.0,
                "mean": 1.1,
                "standard_deviation": 1.4,
            },
        },
    }
    document.update(overrides)
    return document
