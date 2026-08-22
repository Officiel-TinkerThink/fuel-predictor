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
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    # A request actually arriving over HTTPS always gets a Secure cookie
    # regardless of this flag; set it true only to force Secure even when the
    # app cannot see the original scheme (for example behind a proxy that has
    # not been configured to forward it yet).
    session_cookies_require_https: bool = False
    # Bounds on an uploaded model package (ADR 0009). Defaults are generous
    # for a small ONNX/skops pipeline and deliberately far below the plan's
    # 1-2 GB VM envelope, so a hostile upload cannot exhaust it.
    model_package_max_archive_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    model_package_max_extracted_bytes: int = Field(default=256 * 1024 * 1024, gt=0)
    model_package_max_member_count: int = Field(default=32, gt=0)
    model_package_max_compression_ratio: int = Field(default=100, gt=0)
    # Promotion eligibility (plan validation step 8). These gate whether an
    # administrator *may* promote; promotion itself stays manual per ADR 0004.
    promotion_max_mae_regression_ratio: float = Field(default=1.1, gt=0)
    promotion_minimum_test_set_size: int = Field(default=30, ge=1)
    # Where accepted model packages are retained. Retention here is a
    # correctness concern, not just disk hygiene (ADR 0010): rollback can only
    # return to a version whose bytes still exist.
    model_artifact_directory: Path = Path(".fuel_predictor/model-packages")
    supported_feature_contract_versions: str = "baseline-v1"
    supported_runtime_compatibility_versions: str = "onnxruntime-1.20,skops-0.11"

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
