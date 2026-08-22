import pytest
from pydantic import ValidationError

from fuel_predictor.configuration import ApplicationSettings


def test_database_url_is_read_from_the_application_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FUEL_PREDICTOR_DATABASE_URL",
        "postgresql+psycopg://planner:secret@db:5432/fuel_predictor",
    )

    assert ApplicationSettings().database_url == (
        "postgresql+psycopg://planner:secret@db:5432/fuel_predictor"
    )


def test_database_url_rejects_an_unconfigured_driver() -> None:
    with pytest.raises(ValidationError, match="FUEL_PREDICTOR_DATABASE_URL"):
        ApplicationSettings(database_url="postgresql://planner:secret@db/fuel_predictor")


def test_monitoring_thresholds_are_validated_at_the_application_boundary() -> None:
    settings = ApplicationSettings(
        missing_actual_after_days=3,
        monitoring_drift_share_threshold=0.4,
        monitoring_rolling_error_window=5,
        monitoring_min_matched_outcomes=2,
    )

    assert settings.missing_actual_after_days == 3
    assert settings.monitoring_drift_share_threshold == 0.4
    with pytest.raises(ValidationError, match="monitoring_drift_share_threshold"):
        ApplicationSettings(monitoring_drift_share_threshold=1.1)
