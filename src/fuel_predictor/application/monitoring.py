from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fuel_predictor.application.baseline_predictions import ActiveModelVersionReader
from fuel_predictor.domain.monitoring import (
    CategoryDegradation,
    DatasetValidationSummary,
    FeatureDriftSummary,
    MissingActualPrediction,
    MonitoringAlert,
    MonitoringAlertKind,
    MonitoringAlertSeverity,
    RollingErrorPoint,
    TimedPredictionOutcome,
    UnresolvedDataQualityIssue,
)
from fuel_predictor.domain.prediction import ModelVersion


class MonitoringDataReader(Protocol):
    def get_dataset_validation_summaries(self) -> Sequence[DatasetValidationSummary]: ...

    def get_unresolved_data_quality_issues(self) -> Sequence[UnresolvedDataQualityIssue]: ...

    def get_predictions_missing_actual(
        self, older_than: datetime
    ) -> Sequence[MissingActualPrediction]: ...

    def get_reference_feature_rows(
        self, dataset_version_id: str
    ) -> Sequence[dict[str, str | float]]: ...

    def get_current_feature_rows(
        self, model_version_id: str
    ) -> Sequence[dict[str, str | float]]: ...

    def get_timed_prediction_outcomes(self) -> Sequence[TimedPredictionOutcome]: ...


class MonitoringAlertStore(Protocol):
    def reconcile(
        self, active_alerts: Sequence[MonitoringAlert], observed_at: datetime
    ) -> Sequence[MonitoringAlert]: ...


class FeatureDriftAnalyzer(Protocol):
    def analyze(
        self,
        reference_rows: Sequence[dict[str, str | float]],
        current_rows: Sequence[dict[str, str | float]],
        drift_share_threshold: float,
    ) -> FeatureDriftSummary: ...


@dataclass(frozen=True, slots=True)
class MonitoringDashboard:
    generated_at: datetime
    dataset_validation_summaries: tuple[DatasetValidationSummary, ...]
    unresolved_data_quality_issues: tuple[UnresolvedDataQualityIssue, ...]
    missing_actual_predictions: tuple[MissingActualPrediction, ...]
    feature_drift: FeatureDriftSummary
    rolling_error_trend: tuple[RollingErrorPoint, ...]
    category_degradation: tuple[CategoryDegradation, ...]
    active_alerts: tuple[MonitoringAlert, ...]
    missing_actual_after_days: int
    rolling_error_window: int
    degradation_mae_threshold_liters: float

    @property
    def unresolved_data_quality_issue_count(self) -> int:
        return len(self.unresolved_data_quality_issues)

    @property
    def missing_actual_prediction_count(self) -> int:
        return len(self.missing_actual_predictions)


@dataclass(frozen=True, slots=True)
class GetMonitoringDashboard:
    data_reader: MonitoringDataReader
    model_reader: ActiveModelVersionReader
    alert_store: MonitoringAlertStore
    drift_analyzer: FeatureDriftAnalyzer
    missing_actual_after_days: int
    drift_share_threshold: float
    rolling_error_window: int
    degradation_mae_threshold_liters: float
    minimum_matched_outcomes: int
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self) -> MonitoringDashboard:
        observed_at = self.now()
        summaries = tuple(self.data_reader.get_dataset_validation_summaries())
        issues = tuple(self.data_reader.get_unresolved_data_quality_issues())
        missing = tuple(
            self.data_reader.get_predictions_missing_actual(
                observed_at - timedelta(days=self.missing_actual_after_days)
            )
        )
        active_model = self.model_reader.get_active()
        drift = self._feature_drift(active_model)
        outcomes = tuple(self.data_reader.get_timed_prediction_outcomes())
        trend = _rolling_error_trend(outcomes, self.rolling_error_window)
        degradation = _category_degradation(
            outcomes,
            self.rolling_error_window,
            self.degradation_mae_threshold_liters,
            self.minimum_matched_outcomes,
        )
        alerts = _alerts_for(issues, missing, drift, degradation, observed_at)
        reconciled = tuple(self.alert_store.reconcile(alerts, observed_at))
        active_alerts = tuple(alert for alert in reconciled if alert.resolved_at is None)
        return MonitoringDashboard(
            generated_at=observed_at,
            dataset_validation_summaries=summaries,
            unresolved_data_quality_issues=issues,
            missing_actual_predictions=missing,
            feature_drift=drift,
            rolling_error_trend=trend,
            category_degradation=degradation,
            active_alerts=active_alerts,
            missing_actual_after_days=self.missing_actual_after_days,
            rolling_error_window=self.rolling_error_window,
            degradation_mae_threshold_liters=self.degradation_mae_threshold_liters,
        )

    def _feature_drift(self, active_model: ModelVersion | None) -> FeatureDriftSummary:
        if active_model is None:
            return FeatureDriftSummary(
                0, 0, "no_active_model", None, self.drift_share_threshold, ()
            )
        return self.drift_analyzer.analyze(
            self.data_reader.get_reference_feature_rows(active_model.dataset_version_id),
            self.data_reader.get_current_feature_rows(active_model.model_version_id),
            self.drift_share_threshold,
        )


def _rolling_error_trend(
    outcomes: Sequence[TimedPredictionOutcome], window: int
) -> tuple[RollingErrorPoint, ...]:
    ordered = sorted(
        outcomes, key=lambda item: (item.actual_recorded_at, item.prediction_created_at)
    )
    return tuple(
        RollingErrorPoint(
            observed_at=outcome.actual_recorded_at,
            matched_record_count=len(ordered[max(0, index - window + 1) : index + 1]),
            mae_liters=_mae(ordered[max(0, index - window + 1) : index + 1]),
        )
        for index, outcome in enumerate(ordered)
    )


def _category_degradation(
    outcomes: Sequence[TimedPredictionOutcome],
    window: int,
    threshold: float,
    minimum_count: int,
) -> tuple[CategoryDegradation, ...]:
    categories = sorted({outcome.vehicle_category for outcome in outcomes}, key=str)
    result: list[CategoryDegradation] = []
    for category in categories:
        category_outcomes = sorted(
            (outcome for outcome in outcomes if outcome.vehicle_category == category),
            key=lambda item: (item.actual_recorded_at, item.prediction_created_at),
        )
        recent = category_outcomes[-window:]
        mae = _mae(recent) if recent else None
        result.append(
            CategoryDegradation(
                vehicle_category=category,
                matched_record_count=len(category_outcomes),
                rolling_mae_liters=mae,
                threshold_liters=threshold,
                degraded=bool(mae is not None and len(recent) >= minimum_count and mae > threshold),
            )
        )
    return tuple(result)


def _mae(outcomes: Sequence[TimedPredictionOutcome]) -> float:
    return sum(
        abs(item.estimated_fuel_requirement_liters - item.actual_fuel_liters) for item in outcomes
    ) / len(outcomes)


def _alerts_for(
    issues: Sequence[UnresolvedDataQualityIssue],
    missing: Sequence[MissingActualPrediction],
    drift: FeatureDriftSummary,
    degradation: Sequence[CategoryDegradation],
    observed_at: datetime,
) -> tuple[MonitoringAlert, ...]:
    alerts: list[MonitoringAlert] = []
    for issue in issues:
        alerts.append(
            _alert(
                f"data_quality:{issue.dataset_version_id}:{issue.sheet_name}:{issue.row_number}",
                MonitoringAlertKind.DATA_QUALITY,
                MonitoringAlertSeverity.WARNING,
                f"Data {issue.dataset_version_id} memiliki baris yang masih perlu diperbaiki.",
                {"dataset_version_id": issue.dataset_version_id, "row_number": issue.row_number},
                observed_at,
            )
        )
    for prediction in missing:
        alerts.append(
            _alert(
                f"missing_actual:{prediction.operation_id}",
                MonitoringAlertKind.MISSING_ACTUAL,
                MonitoringAlertSeverity.WARNING,
                f"Prediksi untuk {prediction.operation_id} belum memiliki bahan bakar aktual.",
                {
                    "operation_id": prediction.operation_id,
                    "prediction_id": prediction.prediction_id,
                },
                observed_at,
            )
        )
    if (
        drift.status == "ready"
        and drift.drift_share is not None
        and drift.drift_share >= drift.threshold
    ):
        alerts.append(
            _alert(
                "feature_drift:active_model",
                MonitoringAlertKind.FEATURE_DRIFT,
                MonitoringAlertSeverity.WARNING,
                "Distribusi fitur prediksi bergeser melewati ambang pemantauan.",
                {"drift_share": drift.drift_share, "threshold": drift.threshold},
                observed_at,
            )
        )
    for category in degradation:
        if category.degraded:
            alerts.append(
                _alert(
                    f"model_degradation:{category.vehicle_category.value}",
                    MonitoringAlertKind.MODEL_DEGRADATION,
                    MonitoringAlertSeverity.CRITICAL,
                    f"MAE kategori {category.vehicle_category.value} melewati ambang pemantauan.",
                    {
                        "vehicle_category": category.vehicle_category.value,
                        "mae_liters": category.rolling_mae_liters or 0.0,
                        "threshold_liters": category.threshold_liters,
                    },
                    observed_at,
                )
            )
    return tuple(alerts)


def _alert(
    alert_key: str,
    kind: MonitoringAlertKind,
    severity: MonitoringAlertSeverity,
    message: str,
    details: dict[str, str | int | float | bool | list[str]],
    observed_at: datetime,
) -> MonitoringAlert:
    return MonitoringAlert(
        alert_key=alert_key,
        kind=kind,
        severity=severity,
        message=message,
        details=details,
        first_observed_at=observed_at,
        last_observed_at=observed_at,
    )
