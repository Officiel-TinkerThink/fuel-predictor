"""Reference statistics: the drift baseline an externally-trained package must ship."""

from typing import Any

import pytest

from fuel_predictor.application.model_package_ingestion import (
    ParseModelPackageManifest,
    ParseReferenceStatistics,
)
from fuel_predictor.domain.model_package import (
    CategoricalFeatureSummary,
    ModelPackageValidationError,
    NumericFeatureSummary,
)
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    REFERENCE_STATISTICS_SCHEMA,
    JsonSchemaManifestValidator,
    JsonSchemaValidator,
)
from tests.model_package_fixtures import (
    FEATURE_CONTRACT_VERSION,
    RUNTIME_VERSION,
    valid_manifest,
    valid_reference_statistics,
)


def _manifest() -> Any:
    return ParseModelPackageManifest(
        schema_validator=JsonSchemaManifestValidator(),
        supported_feature_contract_versions=frozenset({FEATURE_CONTRACT_VERSION}),
        supported_runtime_compatibility_versions=frozenset({RUNTIME_VERSION}),
    ).execute(valid_manifest())


def _parser() -> ParseReferenceStatistics:
    return ParseReferenceStatistics(
        schema_validator=JsonSchemaValidator(REFERENCE_STATISTICS_SCHEMA)
    )


def _raw(**overrides: Any) -> dict[str, Any]:
    return valid_reference_statistics(**overrides)


def test_valid_reference_statistics_parse_into_domain_summaries() -> None:
    statistics = _parser().execute(_raw(), _manifest())

    assert statistics.row_count == 120
    distance = statistics.features["total_distance_km"]
    assert isinstance(distance, NumericFeatureSummary)
    assert distance.mean == 32.4
    assert distance.quantiles == {"0.5": 30.0}
    category = statistics.features["vehicle_category"]
    assert isinstance(category, CategoricalFeatureSummary)
    assert category.frequencies == {"ANGBER": 1.0}


def test_quantiles_are_optional() -> None:
    statistics = _parser().execute(_raw(), _manifest())

    lifting = statistics.features["lifting_hours"]
    assert isinstance(lifting, NumericFeatureSummary)
    assert lifting.quantiles == {}


def test_a_feature_the_model_uses_but_the_baseline_omits_is_rejected() -> None:
    """A baseline missing a feature cannot produce a meaningful drift verdict."""
    document = _raw()
    del document["features"]["lifting_hours"]

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(document, _manifest())

    assert any("lifting_hours" in message for _field, message in excinfo.value.errors)


def test_a_baseline_feature_the_manifest_does_not_declare_is_rejected() -> None:
    document = _raw()
    document["features"]["phase_of_moon"] = {"kind": "categorical", "frequencies": {"full": 1.0}}

    with pytest.raises(ModelPackageValidationError) as excinfo:
        _parser().execute(document, _manifest())

    assert any("phase_of_moon" in message for _field, message in excinfo.value.errors)


def test_a_zero_row_baseline_is_rejected() -> None:
    with pytest.raises(ModelPackageValidationError):
        _parser().execute(_raw(row_count=0), _manifest())


def test_a_summary_that_is_neither_numeric_nor_categorical_is_rejected() -> None:
    document = _raw()
    document["features"]["total_distance_km"] = {"kind": "mysterious", "value": 1}

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(document, _manifest())


def test_a_frequency_outside_zero_to_one_is_rejected() -> None:
    document = _raw()
    document["features"]["vehicle_category"] = {
        "kind": "categorical",
        "frequencies": {"ANGBER": 1.5},
    }

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(document, _manifest())


def test_a_negative_standard_deviation_is_rejected() -> None:
    document = _raw()
    document["features"]["lifting_hours"]["standard_deviation"] = -1.0

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(document, _manifest())
