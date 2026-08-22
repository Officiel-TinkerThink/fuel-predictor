from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    """Validated runtime configuration for delivery and infrastructure layers."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FUEL_PREDICTOR_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://fuel_predictor:fuel_predictor@localhost:5432/fuel_predictor"
    )
    mlflow_tracking_directory: Path = Path(".fuel_predictor/mlruns")
    mlflow_tracking_uri: str | None = None
    initial_safety_margin_liters: float = Field(default=5.0, ge=0)
    max_active_model_mae_liters: float = Field(default=5.0, gt=0)
    missing_actual_after_days: int = Field(default=7, ge=1)
    monitoring_drift_share_threshold: float = Field(default=0.5, gt=0, le=1)
    monitoring_rolling_error_window: int = Field(default=7, ge=1)
    monitoring_min_matched_outcomes: int = Field(default=3, ge=1)
    google_maps_api_key: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if value.startswith(("postgresql+psycopg://", "sqlite+pysqlite://")):
            return value
        message = (
            "FUEL_PREDICTOR_DATABASE_URL harus menggunakan driver "
            "postgresql+psycopg atau sqlite+pysqlite untuk pengujian."
        )
        raise ValueError(message)
