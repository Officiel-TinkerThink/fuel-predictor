from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import select

from fuel_predictor.application.monitoring import MonitoringAlertStore, MonitoringDataReader
from fuel_predictor.application.prediction_features import feature_values
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.monitoring import (
    DatasetValidationSummary,
    MissingActualPrediction,
    MonitoringAlert,
    MonitoringAlertKind,
    MonitoringAlertSeverity,
    TimedPredictionOutcome,
    UnresolvedDataQualityIssue,
)
from fuel_predictor.infrastructure.database import (
    ActualFuelRecordRow,
    DailyOperationRow,
    DataQualityIssueRow,
    DatasetVersionRow,
    HistoricalDailyOperationRow,
    MonitoringAlertRow,
    PredictionRow,
    SessionFactory,
)


class SqlAlchemyMonitoringRepository(MonitoringDataReader, MonitoringAlertStore):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_dataset_validation_summaries(self) -> tuple[DatasetValidationSummary, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(DatasetVersionRow).order_by(DatasetVersionRow.version.desc())
            )
            return tuple(
                DatasetValidationSummary(
                    dataset_version_id=row.dataset_version_id,
                    version=row.version,
                    source_filename=row.source_filename,
                    imported_at=row.imported_at,
                    valid_operation_count=row.valid_operation_count,
                    quarantined_row_count=row.quarantined_row_count,
                    ignored_blank_row_count=row.ignored_blank_row_count,
                )
                for row in rows
            )

    def get_unresolved_data_quality_issues(self) -> tuple[UnresolvedDataQualityIssue, ...]:
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DatasetVersionRow.dataset_version_id,
                    DatasetVersionRow.source_filename,
                    DataQualityIssueRow.sheet_name,
                    DataQualityIssueRow.row_number,
                    DataQualityIssueRow.reasons,
                )
                .join(
                    DataQualityIssueRow,
                    DataQualityIssueRow.dataset_version_id == DatasetVersionRow.dataset_version_id,
                )
                .order_by(DatasetVersionRow.version.desc(), DataQualityIssueRow.row_number)
            ).all()
        return tuple(
            UnresolvedDataQualityIssue(
                dataset_version_id=row.dataset_version_id,
                source_filename=row.source_filename,
                sheet_name=row.sheet_name,
                row_number=row.row_number,
                messages=tuple(item["message"] for item in row.reasons),
            )
            for row in rows
        )

    def get_predictions_missing_actual(
        self, older_than: datetime
    ) -> tuple[MissingActualPrediction, ...]:
        latest_prediction_id = (
            select(PredictionRow.prediction_id)
            .where(PredictionRow.operation_id == DailyOperationRow.operation_id)
            .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
            .limit(1)
            .correlate(DailyOperationRow)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    PredictionRow.prediction_id,
                    PredictionRow.operation_id,
                    PredictionRow.created_at,
                    DailyOperationRow.vehicle_category,
                )
                .select_from(DailyOperationRow)
                .join(PredictionRow, PredictionRow.prediction_id == latest_prediction_id)
                .outerjoin(
                    ActualFuelRecordRow,
                    ActualFuelRecordRow.operation_id == DailyOperationRow.operation_id,
                )
                .where(
                    ActualFuelRecordRow.operation_id.is_(None),
                    PredictionRow.created_at <= older_than,
                )
                .order_by(PredictionRow.created_at)
            ).all()
        return tuple(
            MissingActualPrediction(
                prediction_id=row.prediction_id,
                operation_id=row.operation_id,
                created_at=row.created_at,
                vehicle_category=VehicleCategory(row.vehicle_category),
            )
            for row in rows
        )

    def get_reference_feature_rows(
        self, dataset_version_id: str
    ) -> tuple[dict[str, str | float], ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(HistoricalDailyOperationRow)
                .where(HistoricalDailyOperationRow.dataset_version_id == dataset_version_id)
                .order_by(HistoricalDailyOperationRow.source_order)
            )
            return tuple(_feature_values_from_historical(row) for row in rows)

    def get_current_feature_rows(self, model_version_id: str) -> tuple[dict[str, str | float], ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(PredictionRow)
                .where(PredictionRow.model_version_id == model_version_id)
                .order_by(PredictionRow.created_at)
            )
            return tuple(cast(dict[str, str | float], row.feature_values) for row in rows)

    def get_timed_prediction_outcomes(self) -> tuple[TimedPredictionOutcome, ...]:
        latest_prediction_id = (
            select(PredictionRow.prediction_id)
            .where(PredictionRow.operation_id == ActualFuelRecordRow.operation_id)
            .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
            .limit(1)
            .correlate(ActualFuelRecordRow)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    DailyOperationRow.vehicle_category,
                    PredictionRow.estimated_fuel_requirement_liters,
                    PredictionRow.created_at,
                    ActualFuelRecordRow.actual_fuel_liters,
                    ActualFuelRecordRow.recorded_at,
                )
                .select_from(ActualFuelRecordRow)
                .join(
                    DailyOperationRow,
                    DailyOperationRow.operation_id == ActualFuelRecordRow.operation_id,
                )
                .join(PredictionRow, PredictionRow.prediction_id == latest_prediction_id)
            ).all()
        return tuple(
            TimedPredictionOutcome(
                vehicle_category=VehicleCategory(row.vehicle_category),
                estimated_fuel_requirement_liters=row.estimated_fuel_requirement_liters,
                actual_fuel_liters=row.actual_fuel_liters,
                prediction_created_at=row.created_at,
                actual_recorded_at=row.recorded_at,
            )
            for row in rows
        )

    def reconcile(
        self, active_alerts: Sequence[MonitoringAlert], observed_at: datetime
    ) -> tuple[MonitoringAlert, ...]:
        active_keys = {alert.alert_key for alert in active_alerts}
        with self._session_factory.begin() as session:
            persisted: list[MonitoringAlertRow] = []
            for alert in active_alerts:
                row = session.get(MonitoringAlertRow, alert.alert_key)
                if row is None:
                    row = MonitoringAlertRow(
                        alert_key=alert.alert_key,
                        kind=alert.kind.value,
                        severity=alert.severity.value,
                        message=alert.message,
                        details=cast(dict[str, object], alert.details),
                        first_observed_at=observed_at,
                        last_observed_at=observed_at,
                        resolved_at=None,
                    )
                    session.add(row)
                else:
                    row.kind = alert.kind.value
                    row.severity = alert.severity.value
                    row.message = alert.message
                    row.details = cast(dict[str, object], alert.details)
                    row.last_observed_at = observed_at
                    row.resolved_at = None
                persisted.append(row)
            existing_active = session.scalars(
                select(MonitoringAlertRow).where(MonitoringAlertRow.resolved_at.is_(None))
            )
            for row in existing_active:
                if row.alert_key not in active_keys:
                    row.resolved_at = observed_at
            session.flush()
            return tuple(_to_monitoring_alert(row) for row in persisted)


def _feature_values_from_historical(row: HistoricalDailyOperationRow) -> dict[str, str | float]:
    return feature_values(
        DailyOperation(
            operation_id=row.operation_id,
            vehicle_category=VehicleCategory(row.vehicle_category),
            activity_mode=ActivityMode(row.activity_mode),
            lifting_hours=row.lifting_hours,
            total_distance_km=row.total_distance_km,
            distance_source=DistanceSource(row.distance_source),
        )
    )


def _to_monitoring_alert(row: MonitoringAlertRow) -> MonitoringAlert:
    return MonitoringAlert(
        alert_key=row.alert_key,
        kind=MonitoringAlertKind(row.kind),
        severity=MonitoringAlertSeverity(row.severity),
        message=row.message,
        details=cast(dict[str, str | int | float | bool | list[str]], row.details),
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        resolved_at=row.resolved_at,
    )
