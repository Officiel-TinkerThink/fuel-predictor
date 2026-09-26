"""The monitoring checks, wired from settings once.

The web app and the scheduled `python -m fuel_predictor monitor` both run
them; built in two places, a threshold added to one would have made the
scheduled check and the page disagree about the same data.
"""

from fuel_predictor.application.baseline_predictions import ActiveModelVersionReader
from fuel_predictor.application.monitoring import (
    GetMonitoringDashboard,
    MonitoringAlertStore,
    MonitoringDataReader,
)
from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.configuration import ApplicationSettings
from fuel_predictor.infrastructure.evidently_drift import EvidentlyFeatureDriftAnalyzer


def build_monitoring_dashboard(
    settings: ApplicationSettings,
    data: MonitoringDataReader,
    models: ActiveModelVersionReader,
    alerts: MonitoringAlertStore,
    vehicle_catalog: VehicleCatalog,
) -> GetMonitoringDashboard:
    return GetMonitoringDashboard(
        data,
        models,
        alerts,
        EvidentlyFeatureDriftAnalyzer(),
        settings.missing_actual_after_days,
        settings.monitoring_drift_share_threshold,
        settings.monitoring_rolling_error_window,
        settings.max_active_model_mae_liters,
        settings.monitoring_min_matched_outcomes,
        vehicle_catalog,
    )
