"""Promotion eligibility (plan validation step 8).

Eligibility is not promotion: ADR 0004 keeps promotion manual, so every test
here is about whether an operator is *allowed* to promote, never about
anything activating on its own.
"""

from typing import Any

import pytest

from fuel_predictor.application.model_package_ingestion import ParseModelPackageManifest
from fuel_predictor.application.model_promotion_policy import (
    EvaluateCandidateAgainstPolicy,
    PromotionPolicy,
)
from fuel_predictor.domain.model_package import ManifestMetrics
from fuel_predictor.infrastructure.jsonschema_manifest_validator import (
    JsonSchemaManifestValidator,
)
from tests.model_package_fixtures import (
    FEATURE_CONTRACT_VERSION,
    RUNTIME_VERSION,
    valid_manifest,
)


def _manifest(**overrides: Any) -> Any:
    return ParseModelPackageManifest(
        schema_validator=JsonSchemaManifestValidator(),
        supported_feature_contract_versions=frozenset({FEATURE_CONTRACT_VERSION}),
        supported_runtime_compatibility_versions=frozenset({RUNTIME_VERSION}),
    ).execute(valid_manifest(**overrides))


def _metrics(
    mae: float = 3.0,
    rmse: float = 4.0,
    smape: float = 12.0,
    coverage: float = 90.0,
) -> ManifestMetrics:
    return ManifestMetrics(
        mae=mae, rmse=rmse, smape_percent=smape, interval_coverage_percent=coverage
    )


def _policy(**overrides: Any) -> EvaluateCandidateAgainstPolicy:
    settings: dict[str, Any] = {
        "max_mae_liters": 5.0,
        "max_mae_regression_ratio": 1.1,
        "minimum_test_set_size": 30,
    }
    settings.update(overrides)
    return EvaluateCandidateAgainstPolicy(policy=PromotionPolicy(**settings))


def test_a_candidate_better_than_the_active_model_is_eligible() -> None:
    result = _policy().execute(_manifest(), active_metrics=_metrics(mae=4.0))

    assert result.eligible is True
    assert result.reasons == ()


def test_a_candidate_over_the_absolute_ceiling_is_not_eligible() -> None:
    manifest = _manifest(
        metrics={
            "overall": {
                "mae": 9.9,
                "rmse": 11.0,
                "smape_percent": 30.0,
                "interval_coverage_percent": 88.0,
            }
        }
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=9.5))

    assert result.eligible is False
    assert any("melebihi ambang" in reason for reason in result.reasons)


def test_a_candidate_meaningfully_worse_than_the_active_model_is_not_eligible() -> None:
    """Under the absolute ceiling but a clear regression: still blocked.

    This is why a ceiling alone is not enough — 4.9 L passes the 5 L ceiling
    while being far worse than the 2.0 L model currently serving.
    """
    manifest = _manifest(
        metrics={
            "overall": {
                "mae": 4.9,
                "rmse": 5.2,
                "smape_percent": 18.0,
                "interval_coverage_percent": 89.0,
            }
        }
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=2.0))

    assert result.eligible is False
    assert any("model aktif" in reason for reason in result.reasons)


def test_a_slightly_worse_candidate_within_the_allowed_ratio_stays_eligible() -> None:
    """Noise-level differences must not block promotion outright."""
    manifest = _manifest(
        metrics={
            "overall": {
                "mae": 3.15,
                "rmse": 4.0,
                "smape_percent": 12.0,
                "interval_coverage_percent": 90.0,
            }
        }
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=3.0))

    assert result.eligible is True


def test_a_small_test_set_blocks_promotion() -> None:
    result = _policy().execute(_manifest(test_set_size=5), active_metrics=_metrics(mae=4.0))

    assert result.eligible is False
    assert any("set uji" in reason for reason in result.reasons)


def test_no_active_model_is_stated_explicitly_rather_than_read_as_no_regression() -> None:
    result = _policy().execute(_manifest(), active_metrics=None)

    assert result.eligible is True
    assert any("Belum ada model aktif" in warning for warning in result.warnings)


def test_a_zero_mae_active_model_does_not_produce_a_division_error() -> None:
    """A ratio against zero is meaningless, so compare absolutely instead."""
    result = _policy().execute(_manifest(), active_metrics=_metrics(mae=0.0))

    assert result.eligible is False
    assert any("lebih buruk" in reason for reason in result.reasons)


def test_a_perfect_active_model_and_a_perfect_candidate_is_not_a_regression() -> None:
    manifest = _manifest(
        metrics={
            "overall": {
                "mae": 0.0,
                "rmse": 0.0,
                "smape_percent": 0.0,
                "interval_coverage_percent": 100.0,
            }
        }
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=0.0, coverage=100.0))

    assert result.eligible is True


def test_dropping_interval_coverage_warns_without_blocking() -> None:
    """A better point estimate with worse calibration is the operator's call."""
    manifest = _manifest(
        metrics={
            "overall": {
                "mae": 2.0,
                "rmse": 3.0,
                "smape_percent": 9.0,
                "interval_coverage_percent": 70.0,
            }
        }
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=3.0, coverage=92.0))

    assert result.eligible is True
    assert any("Cakupan interval turun" in warning for warning in result.warnings)


def test_every_blocking_reason_is_reported_together() -> None:
    manifest = _manifest(
        test_set_size=2,
        metrics={
            "overall": {
                "mae": 20.0,
                "rmse": 22.0,
                "smape_percent": 60.0,
                "interval_coverage_percent": 40.0,
            }
        },
    )

    result = _policy().execute(manifest, active_metrics=_metrics(mae=2.0))

    assert result.eligible is False
    assert len(result.reasons) == 3


@pytest.mark.parametrize("eligible", [True, False])
def test_the_summary_never_claims_a_candidate_was_promoted(eligible: bool) -> None:
    """ADR 0004: this step decides eligibility only, and must not imply otherwise."""
    active = _metrics(mae=4.0) if eligible else _metrics(mae=0.5)
    result = _policy().execute(_manifest(), active_metrics=active)

    assert result.eligible is eligible
    assert "dipromosikan" not in result.summary
    assert "aktif" not in result.summary
