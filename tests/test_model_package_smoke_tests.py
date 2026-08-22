"""Smoke-test contract and runner (ADR 0009 package format, ADR 0010 step 2)."""

from typing import Any

import pytest

from fuel_predictor.application.model_package_ingestion import (
    DeterministicSmokeTestRunner,
    ParseSmokeTests,
)
from fuel_predictor.domain.model_package import ModelPackageValidationError, SmokeTestCase
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    SMOKE_TESTS_SCHEMA,
    JsonSchemaValidator,
)


def _parser() -> ParseSmokeTests:
    return ParseSmokeTests(schema_validator=JsonSchemaValidator(SMOKE_TESTS_SCHEMA))


def _raw(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "cases": [
            {
                "name": "angkut 30 km",
                "features": {"vehicle_category": "ANGBER", "total_distance_km": 30.0},
                "expected_prediction": 21.5,
                "tolerance": 0.05,
            }
        ]
    }
    document.update(overrides)
    return document


class _Model:
    """Stand-in for a loaded model; the runner must not care what backs it."""

    def __init__(self, answer: float | Exception) -> None:
        self.answer = answer

    def predict(self, features: dict[str, Any]) -> float:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_valid_smoke_tests_parse_into_domain_cases() -> None:
    cases = _parser().execute(_raw())

    assert len(cases) == 1
    assert cases[0].name == "angkut 30 km"
    assert cases[0].expected_prediction == 21.5
    assert cases[0].tolerance == 0.05


def test_tolerance_defaults_when_the_package_omits_it() -> None:
    document = _raw()
    del document["cases"][0]["tolerance"]

    cases = _parser().execute(document)

    assert cases[0].tolerance == 0.01


def test_a_package_with_no_cases_is_rejected() -> None:
    """A package asserting nothing about itself cannot be smoke-tested."""
    with pytest.raises(ModelPackageValidationError):
        _parser().execute(_raw(cases=[]))


def test_a_case_missing_its_expected_prediction_is_rejected() -> None:
    document = _raw()
    del document["cases"][0]["expected_prediction"]

    with pytest.raises(ModelPackageValidationError):
        _parser().execute(document)


def test_a_model_answering_within_tolerance_produces_no_failures() -> None:
    runner = DeterministicSmokeTestRunner(cases=_parser().execute(_raw()))

    assert runner.run(_Model(21.53)) == []


def test_a_model_answering_outside_tolerance_fails_with_a_readable_message() -> None:
    runner = DeterministicSmokeTestRunner(cases=_parser().execute(_raw()))

    failures = runner.run(_Model(41.9))

    assert len(failures) == 1
    assert "angkut 30 km" in failures[0]
    assert "21.5" in failures[0] or "21,5" in failures[0]
    assert "41.9" in failures[0] or "41,9" in failures[0]


def test_a_model_that_raises_on_a_declared_case_is_a_failure_not_a_crash() -> None:
    """A model erroring on a case it declared it could answer is the point of this step."""
    runner = DeterministicSmokeTestRunner(cases=_parser().execute(_raw()))

    failures = runner.run(_Model(ValueError("unknown categorical level")))

    assert len(failures) == 1
    assert "gagal memproses" in failures[0]
    assert "unknown categorical level" in failures[0]


def test_every_case_runs_even_after_an_earlier_one_fails() -> None:
    """One pass must surface the full picture, not just the first problem."""
    cases = (
        SmokeTestCase("first", {"x": 1}, expected_prediction=1.0, tolerance=0.0),
        SmokeTestCase("second", {"x": 2}, expected_prediction=2.0, tolerance=0.0),
        SmokeTestCase("third", {"x": 3}, expected_prediction=3.0, tolerance=0.0),
    )
    runner = DeterministicSmokeTestRunner(cases=cases)

    failures = runner.run(_Model(99.0))

    assert len(failures) == 3
    assert [case.name for case in cases] == ["first", "second", "third"]


def test_tolerance_boundary_is_inclusive() -> None:
    """Exactly-at-tolerance passes: a strict boundary would be arbitrary."""
    cases = (SmokeTestCase("edge", {"x": 1}, expected_prediction=10.0, tolerance=0.5),)
    runner = DeterministicSmokeTestRunner(cases=cases)

    assert runner.run(_Model(10.5)) == []
    assert runner.run(_Model(9.5)) == []
    assert runner.run(_Model(10.51)) != []
