from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, File, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    GetPredictionPerformance,
    PerformanceMetrics,
    RecordActualFuel,
    RecordActualFuelCommand,
)
from fuel_predictor.application.baseline_predictions import (
    BaselineModelNotFoundError,
    BaselineTrainingError,
    GenerateFuelPrediction,
    TrainBaselineCandidate,
)
from fuel_predictor.application.bulk_actual_fuel import BulkActualFuel, BulkActualFuelResult
from fuel_predictor.application.bulk_operation_predictions import (
    BulkOperationPrediction,
    BulkOperationPredictionResult,
)
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    CreateDailyOperationCommand,
    DailyOperationNotFoundError,
    GetDailyOperation,
)
from fuel_predictor.application.historical_datasets import (
    DatasetVersionNotFoundError,
    GetDatasetValidOperations,
    HistoricalDatasetImportError,
    HistoricalDatasetImportResult,
    ImportHistoricalDataset,
)
from fuel_predictor.application.model_lifecycle import (
    CandidateModelNotFoundError,
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    ModelComparison,
    ModelPromotionNotAllowedError,
    PromoteCandidateModel,
)
from fuel_predictor.application.monitoring import GetMonitoringDashboard, MonitoringDashboard
from fuel_predictor.domain.actual_fuel import ActualFuelMeasurementSource, ActualFuelRecord
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DailyOperationValidationError,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.historical_dataset import HistoricalDailyOperation, SourceProvenance
from fuel_predictor.domain.monitoring import (
    CategoryDegradation,
    DatasetValidationSummary,
    FeatureDriftSummary,
    MissingActualPrediction,
    MonitoringAlert,
    RollingErrorPoint,
    UnresolvedDataQualityIssue,
)
from fuel_predictor.domain.prediction import FuelPrediction, ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.actual_fuel_template import (
    csv_template as actual_fuel_csv_template,
)
from fuel_predictor.infrastructure.actual_fuel_template import (
    xlsx_template as actual_fuel_xlsx_template,
)
from fuel_predictor.infrastructure.bulk_prediction_template import csv_template, xlsx_template

_UPLOAD_FILE = File(...)


class CreateDailyOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None = None
    total_distance_km: float = Field(gt=0, allow_inf_nan=False)
    distance_source: DistanceSource
    stop_sequence: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("stop_sequence", "stops"),
    )

    @field_validator("stop_sequence")
    @classmethod
    def normalize_stop_sequence(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values]


class DailyOperationResponse(BaseModel):
    operation_id: str
    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None
    total_distance_km: float
    distance_source: DistanceSource
    stop_sequence: list[str] | None = None
    route_distance_manual_fallback: bool | None = None


class DatasetVersionResponse(BaseModel):
    dataset_version_id: str
    version: int
    source_filename: str
    valid_operation_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int


class SourceProvenanceResponse(BaseModel):
    sheet_name: str
    row_number: int
    original_headers: dict[str, str]
    raw_values: dict[str, str | int | float | bool | None]


class HistoricalDailyOperationResponse(BaseModel):
    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None
    total_distance_km: float
    distance_source: DistanceSource
    prepared_fuel_liters: float
    source: SourceProvenanceResponse


class CorrectionReasonResponse(BaseModel):
    field: str
    message: str


class DataQualityIssueResponse(BaseModel):
    sheet_name: str
    row_number: int
    reasons: list[CorrectionReasonResponse]
    raw_values: dict[str, str | int | float | bool | None]


class HistoricalDatasetImportResponse(BaseModel):
    dataset_version: DatasetVersionResponse
    valid_operations: list[HistoricalDailyOperationResponse]
    correction_report: list[DataQualityIssueResponse]


class DatasetOperationsResponse(BaseModel):
    valid_operations: list[HistoricalDailyOperationResponse]


class ModelVersionResponse(BaseModel):
    model_version_id: str
    version: int
    dataset_version_id: str
    feature_version: str
    algorithm: str
    training_row_count: int
    uncertainty_liters: float
    lifecycle_status: ModelLifecycleStatus
    promoted_at: datetime | None
    retired_at: datetime | None


class UncertaintyIntervalResponse(BaseModel):
    lower: float
    upper: float


class PredictionLineageResponse(BaseModel):
    input_operation_id: str
    feature_version: str
    dataset_version_id: str
    model_version_id: str


class FuelPredictionResponse(BaseModel):
    prediction_id: str
    operation_id: str
    estimated_fuel_requirement_liters: float
    recommended_allocation_liters: float
    uncertainty_interval_liters: UncertaintyIntervalResponse
    route_distance_source: DistanceSource
    route_distance_manual_fallback: bool
    model: ModelVersionResponse
    lineage: PredictionLineageResponse
    safety_policy: str
    input_snapshot: dict[str, str | float | bool | list[str] | None]
    feature_values: dict[str, str | float]


class BulkSourceProvenanceResponse(BaseModel):
    source_filename: str
    sheet_name: str
    row_number: int
    original_headers: dict[str, str]
    raw_values: dict[str, str | int | float | bool | None]


class BulkAcceptedRowResponse(BaseModel):
    source: BulkSourceProvenanceResponse
    operation: DailyOperationResponse
    prediction: FuelPredictionResponse


class BulkCorrectionReportRowResponse(BaseModel):
    source: BulkSourceProvenanceResponse
    reasons: list[CorrectionReasonResponse]


class BulkOperationPredictionResponse(BaseModel):
    accepted_row_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int
    accepted_rows: list[BulkAcceptedRowResponse]
    correction_report: list[BulkCorrectionReportRowResponse]


class ActualFuelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_fuel_liters: float = Field(gt=0, allow_inf_nan=False)
    measurement_source: ActualFuelMeasurementSource = ActualFuelMeasurementSource.MANUAL_ENTRY


class ActualFuelResponse(BaseModel):
    operation_id: str
    actual_fuel_liters: float
    measurement_source: ActualFuelMeasurementSource
    status: str


class BulkActualFuelAcceptedRowResponse(BaseModel):
    source: BulkSourceProvenanceResponse
    actual_fuel: ActualFuelResponse


class BulkActualFuelResponse(BaseModel):
    accepted_row_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int
    accepted_rows: list[BulkActualFuelAcceptedRowResponse]
    correction_report: list[BulkCorrectionReportRowResponse]


class PerformanceMetricsResponse(BaseModel):
    matched_record_count: int
    mae_liters: float | None
    rmse_liters: float | None
    smape_percent: float | None
    interval_coverage_percent: float | None


class CategoryPerformanceResponse(PerformanceMetricsResponse):
    vehicle_category: VehicleCategory


class PredictionPerformanceResponse(BaseModel):
    overall: PerformanceMetricsResponse
    by_vehicle_category: list[CategoryPerformanceResponse]


class CategoryModelComparisonResponse(BaseModel):
    vehicle_category: VehicleCategory
    candidate: PerformanceMetricsResponse
    active: PerformanceMetricsResponse | None


class ModelComparisonResponse(BaseModel):
    candidate: ModelVersionResponse
    active_model: ModelVersionResponse | None
    candidate_overall: PerformanceMetricsResponse
    active_overall: PerformanceMetricsResponse | None
    by_vehicle_category: list[CategoryModelComparisonResponse]


class ModelGovernanceDashboardResponse(BaseModel):
    active_model: ModelVersionResponse | None
    active_performance: PerformanceMetricsResponse | None
    candidate_models: list[ModelVersionResponse]
    retraining_recommended: bool
    recommendation: str


class DatasetValidationSummaryResponse(BaseModel):
    dataset_version_id: str
    version: int
    source_filename: str
    imported_at: datetime
    valid_operation_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int


class UnresolvedDataQualityIssueResponse(BaseModel):
    dataset_version_id: str
    source_filename: str
    sheet_name: str
    row_number: int
    messages: list[str]


class MissingActualPredictionResponse(BaseModel):
    prediction_id: str
    operation_id: str
    created_at: datetime
    vehicle_category: VehicleCategory


class FeatureDriftResponse(BaseModel):
    reference_row_count: int
    current_row_count: int
    status: str
    drift_share: float | None
    threshold: float
    drifting_features: list[str]


class RollingErrorPointResponse(BaseModel):
    observed_at: datetime
    matched_record_count: int
    mae_liters: float


class CategoryDegradationResponse(BaseModel):
    vehicle_category: VehicleCategory
    matched_record_count: int
    rolling_mae_liters: float | None
    threshold_liters: float
    degraded: bool


class MonitoringAlertResponse(BaseModel):
    alert_key: str
    kind: str
    severity: str
    message: str
    details: dict[str, str | int | float | bool | list[str]]
    first_observed_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None


class MonitoringDashboardResponse(BaseModel):
    generated_at: datetime
    dataset_validation_summaries: list[DatasetValidationSummaryResponse]
    unresolved_data_quality_issues: list[UnresolvedDataQualityIssueResponse]
    unresolved_data_quality_issue_count: int
    missing_actual_predictions: list[MissingActualPredictionResponse]
    missing_actual_prediction_count: int
    feature_drift: FeatureDriftResponse
    rolling_error_trend: list[RollingErrorPointResponse]
    category_degradation: list[CategoryDegradationResponse]
    active_alerts: list[MonitoringAlertResponse]
    missing_actual_after_days: int
    rolling_error_window: int
    degradation_mae_threshold_liters: float


def build_router(
    create_daily_operation: CreateDailyOperation,
    get_daily_operation: GetDailyOperation,
    import_historical_dataset: ImportHistoricalDataset,
    get_dataset_valid_operations: GetDatasetValidOperations,
    train_baseline_candidate: TrainBaselineCandidate,
    generate_fuel_prediction: GenerateFuelPrediction,
    bulk_operation_prediction: BulkOperationPrediction,
    record_actual_fuel: RecordActualFuel,
    bulk_actual_fuel: BulkActualFuel,
    get_prediction_performance: GetPredictionPerformance,
    promote_candidate_model: PromoteCandidateModel,
    get_candidate_model_comparison: GetCandidateModelComparison,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    get_monitoring_dashboard: GetMonitoringDashboard,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/daily-operations",
        response_model=DailyOperationResponse,
        response_model_exclude_none=True,
        status_code=status.HTTP_201_CREATED,
    )
    def create_operation(request: CreateDailyOperationRequest) -> DailyOperationResponse:
        operation = execute_create(request, create_daily_operation)
        return _operation_response(operation)

    @router.get(
        "/api/v1/daily-operations/{operation_id}",
        response_model=DailyOperationResponse,
        response_model_exclude_none=True,
    )
    def get_operation(operation_id: str) -> DailyOperationResponse:
        operation = get_daily_operation.execute(operation_id)
        return _operation_response(operation)

    @router.post(
        "/api/v1/historical-datasets",
        response_model=HistoricalDatasetImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_dataset(file: UploadFile = _UPLOAD_FILE) -> HistoricalDatasetImportResponse:
        result = import_historical_dataset.execute(
            file.filename or "berkas-impor", await file.read()
        )
        return _historical_dataset_import_response(result)

    @router.get("/api/v1/bulk-operation-predictions/template")
    def download_bulk_template(
        format: Literal["xlsx", "csv"] = Query(default="xlsx"),
    ) -> Response:
        if format == "csv":
            return Response(
                content=csv_template(),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="template-prediksi-operasi.csv"'
                },
            )
        return Response(
            content=xlsx_template(),
            media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            headers={
                "Content-Disposition": 'attachment; filename="template-prediksi-operasi.xlsx"'
            },
        )

    @router.post(
        "/api/v1/bulk-operation-predictions",
        response_model=BulkOperationPredictionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def predict_bulk_operations(
        file: UploadFile = _UPLOAD_FILE,
    ) -> BulkOperationPredictionResponse:
        result = bulk_operation_prediction.execute(
            file.filename or "berkas-prediksi-operasi", await file.read()
        )
        return _bulk_prediction_response(result)

    @router.get("/api/v1/bulk-actual-fuel/template")
    def download_bulk_actual_fuel_template(
        format: Literal["xlsx", "csv"] = Query(default="xlsx"),
    ) -> Response:
        if format == "csv":
            return Response(
                content=actual_fuel_csv_template(),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="template-bbm-aktual.csv"'},
            )
        return Response(
            content=actual_fuel_xlsx_template(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="template-bbm-aktual.xlsx"'},
        )

    @router.post(
        "/api/v1/bulk-actual-fuel",
        response_model=BulkActualFuelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def record_bulk_actual_fuel(file: UploadFile = _UPLOAD_FILE) -> BulkActualFuelResponse:
        result = bulk_actual_fuel.execute(file.filename or "berkas-bbm-aktual", await file.read())
        return _bulk_actual_fuel_response(result)

    @router.get(
        "/api/v1/dataset-versions/{dataset_version_id}/daily-operations",
        response_model=DatasetOperationsResponse,
    )
    def get_dataset_operations(dataset_version_id: str) -> DatasetOperationsResponse:
        operations = get_dataset_valid_operations.execute(dataset_version_id)
        return DatasetOperationsResponse(
            valid_operations=[_historical_operation_response(operation) for operation in operations]
        )

    @router.post(
        "/api/v1/dataset-versions/{dataset_version_id}/baseline-candidates",
        response_model=ModelVersionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def train_baseline(dataset_version_id: str) -> ModelVersionResponse:
        return _model_response(train_baseline_candidate.execute(dataset_version_id))

    @router.get(
        "/api/v1/model-candidates/{model_version_id}/comparison",
        response_model=ModelComparisonResponse,
    )
    def compare_candidate(model_version_id: str) -> ModelComparisonResponse:
        return _model_comparison_response(get_candidate_model_comparison.execute(model_version_id))

    @router.post(
        "/api/v1/model-candidates/{model_version_id}/promote",
        response_model=ModelVersionResponse,
    )
    def promote_candidate(model_version_id: str) -> ModelVersionResponse:
        return _model_response(promote_candidate_model.execute(model_version_id))

    @router.get(
        "/api/v1/model-governance-dashboard",
        response_model=ModelGovernanceDashboardResponse,
    )
    def get_model_dashboard() -> ModelGovernanceDashboardResponse:
        dashboard = get_model_governance_dashboard.execute()
        return ModelGovernanceDashboardResponse(
            active_model=_model_response(dashboard.active_model)
            if dashboard.active_model
            else None,
            active_performance=(
                _performance_metrics_response(dashboard.active_performance)
                if dashboard.active_performance
                else None
            ),
            candidate_models=[_model_response(model) for model in dashboard.candidate_models],
            retraining_recommended=dashboard.retraining_recommended,
            recommendation=dashboard.recommendation,
        )

    @router.get("/api/v1/monitoring-dashboard", response_model=MonitoringDashboardResponse)
    def get_monitoring() -> MonitoringDashboardResponse:
        return _monitoring_dashboard_response(get_monitoring_dashboard.execute())

    @router.post(
        "/api/v1/daily-operations/{operation_id}/predictions",
        response_model=FuelPredictionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_prediction(operation_id: str) -> FuelPredictionResponse:
        return _prediction_response(generate_fuel_prediction.execute(operation_id))

    @router.post(
        "/api/v1/daily-operations/{operation_id}/actual-fuel",
        response_model=ActualFuelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def record_actual(operation_id: str, request: ActualFuelRequest) -> ActualFuelResponse:
        return _actual_fuel_response(
            record_actual_fuel.execute(
                RecordActualFuelCommand(
                    operation_id=operation_id,
                    actual_fuel_liters=request.actual_fuel_liters,
                    measurement_source=request.measurement_source,
                )
            )
        )

    @router.get("/api/v1/prediction-performance", response_model=PredictionPerformanceResponse)
    def get_performance() -> PredictionPerformanceResponse:
        report = get_prediction_performance.execute()
        return PredictionPerformanceResponse(
            overall=_performance_metrics_response(report.overall),
            by_vehicle_category=[
                CategoryPerformanceResponse(
                    vehicle_category=category,
                    **_performance_metrics_response(metrics).model_dump(),
                )
                for category, metrics in report.by_vehicle_category
            ],
        )

    return router


def _model_response(model: ModelVersion) -> ModelVersionResponse:
    return ModelVersionResponse(
        model_version_id=model.model_version_id,
        version=model.version,
        dataset_version_id=model.dataset_version_id,
        feature_version=model.feature_version,
        algorithm=model.algorithm,
        training_row_count=model.training_row_count,
        uncertainty_liters=model.uncertainty_liters,
        lifecycle_status=model.lifecycle_status,
        promoted_at=model.promoted_at,
        retired_at=model.retired_at,
    )


def _model_comparison_response(comparison: ModelComparison) -> ModelComparisonResponse:
    return ModelComparisonResponse(
        candidate=_model_response(comparison.candidate),
        active_model=(
            _model_response(comparison.active_model)
            if comparison.active_model is not None
            else None
        ),
        candidate_overall=_performance_metrics_response(comparison.candidate_overall),
        active_overall=(
            _performance_metrics_response(comparison.active_overall)
            if comparison.active_overall is not None
            else None
        ),
        by_vehicle_category=[
            CategoryModelComparisonResponse(
                vehicle_category=item.vehicle_category,
                candidate=_performance_metrics_response(item.candidate),
                active=_performance_metrics_response(item.active) if item.active else None,
            )
            for item in comparison.by_vehicle_category
        ],
    )


def _operation_response(operation: DailyOperation) -> DailyOperationResponse:
    return DailyOperationResponse(
        operation_id=operation.operation_id,
        vehicle_category=operation.vehicle_category,
        activity_mode=operation.activity_mode,
        lifting_hours=operation.lifting_hours,
        total_distance_km=operation.total_distance_km,
        distance_source=operation.distance_source,
        stop_sequence=list(operation.stop_sequence) if operation.stop_sequence else None,
        route_distance_manual_fallback=(
            operation.route_distance_manual_fallback if operation.stop_sequence else None
        ),
    )


def _prediction_response(prediction: FuelPrediction) -> FuelPredictionResponse:
    model = _model_response(prediction.model)
    return FuelPredictionResponse(
        prediction_id=prediction.prediction_id,
        operation_id=prediction.operation_id,
        estimated_fuel_requirement_liters=prediction.estimated_fuel_requirement_liters,
        recommended_allocation_liters=prediction.recommended_allocation_liters,
        uncertainty_interval_liters=UncertaintyIntervalResponse(
            lower=prediction.uncertainty_lower_liters,
            upper=prediction.uncertainty_upper_liters,
        ),
        route_distance_source=prediction.route_distance_source,
        route_distance_manual_fallback=prediction.route_distance_manual_fallback,
        model=model,
        lineage=PredictionLineageResponse(
            input_operation_id=prediction.operation_id,
            feature_version=prediction.model.feature_version,
            dataset_version_id=prediction.model.dataset_version_id,
            model_version_id=prediction.model.model_version_id,
        ),
        safety_policy=prediction.safety_policy,
        input_snapshot=prediction.input_snapshot,
        feature_values=prediction.feature_values,
    )


def _bulk_prediction_response(
    result: BulkOperationPredictionResult,
) -> BulkOperationPredictionResponse:
    def source_response(source: SourceProvenance) -> BulkSourceProvenanceResponse:
        assert source.source_filename is not None
        return BulkSourceProvenanceResponse(
            source_filename=source.source_filename,
            sheet_name=source.sheet_name,
            row_number=source.row_number,
            original_headers=source.original_headers,
            raw_values=source.raw_values,
        )

    return BulkOperationPredictionResponse(
        accepted_row_count=len(result.accepted_rows),
        quarantined_row_count=len(result.correction_report),
        ignored_blank_row_count=result.ignored_blank_row_count,
        accepted_rows=[
            BulkAcceptedRowResponse(
                source=source_response(row.source),
                operation=_operation_response(row.operation),
                prediction=_prediction_response(row.prediction),
            )
            for row in result.accepted_rows
        ],
        correction_report=[
            BulkCorrectionReportRowResponse(
                source=source_response(issue.source),
                reasons=[
                    CorrectionReasonResponse(field=reason.field, message=reason.message)
                    for reason in issue.reasons
                ],
            )
            for issue in result.correction_report
        ],
    )


def _actual_fuel_response(record: ActualFuelRecord) -> ActualFuelResponse:
    return ActualFuelResponse(
        operation_id=record.operation_id,
        actual_fuel_liters=record.actual_fuel_liters,
        measurement_source=record.measurement_source,
        status=record.status.value,
    )


def _bulk_actual_fuel_response(result: BulkActualFuelResult) -> BulkActualFuelResponse:
    def source_response(source: SourceProvenance) -> BulkSourceProvenanceResponse:
        assert source.source_filename is not None
        return BulkSourceProvenanceResponse(
            source_filename=source.source_filename,
            sheet_name=source.sheet_name,
            row_number=source.row_number,
            original_headers=source.original_headers,
            raw_values=source.raw_values,
        )

    return BulkActualFuelResponse(
        accepted_row_count=len(result.accepted_rows),
        quarantined_row_count=len(result.correction_report),
        ignored_blank_row_count=result.ignored_blank_row_count,
        accepted_rows=[
            BulkActualFuelAcceptedRowResponse(
                source=source_response(row.source),
                actual_fuel=_actual_fuel_response(row.actual_fuel),
            )
            for row in result.accepted_rows
        ],
        correction_report=[
            BulkCorrectionReportRowResponse(
                source=source_response(issue.source),
                reasons=[
                    CorrectionReasonResponse(field=reason.field, message=reason.message)
                    for reason in issue.reasons
                ],
            )
            for issue in result.correction_report
        ],
    )


def _performance_metrics_response(metrics: PerformanceMetrics) -> PerformanceMetricsResponse:
    return PerformanceMetricsResponse(
        matched_record_count=metrics.matched_record_count,
        mae_liters=metrics.mae_liters,
        rmse_liters=metrics.rmse_liters,
        smape_percent=metrics.smape_percent,
        interval_coverage_percent=metrics.interval_coverage_percent,
    )


def _monitoring_dashboard_response(dashboard: MonitoringDashboard) -> MonitoringDashboardResponse:
    return MonitoringDashboardResponse(
        generated_at=dashboard.generated_at,
        dataset_validation_summaries=[
            _dataset_validation_summary_response(item)
            for item in dashboard.dataset_validation_summaries
        ],
        unresolved_data_quality_issues=[
            _unresolved_data_quality_issue_response(item)
            for item in dashboard.unresolved_data_quality_issues
        ],
        unresolved_data_quality_issue_count=dashboard.unresolved_data_quality_issue_count,
        missing_actual_predictions=[
            _missing_actual_prediction_response(item)
            for item in dashboard.missing_actual_predictions
        ],
        missing_actual_prediction_count=dashboard.missing_actual_prediction_count,
        feature_drift=_feature_drift_response(dashboard.feature_drift),
        rolling_error_trend=[
            _rolling_error_point_response(item) for item in dashboard.rolling_error_trend
        ],
        category_degradation=[
            _category_degradation_response(item) for item in dashboard.category_degradation
        ],
        active_alerts=[_monitoring_alert_response(item) for item in dashboard.active_alerts],
        missing_actual_after_days=dashboard.missing_actual_after_days,
        rolling_error_window=dashboard.rolling_error_window,
        degradation_mae_threshold_liters=dashboard.degradation_mae_threshold_liters,
    )


def _dataset_validation_summary_response(
    item: DatasetValidationSummary,
) -> DatasetValidationSummaryResponse:
    return DatasetValidationSummaryResponse(
        dataset_version_id=item.dataset_version_id,
        version=item.version,
        source_filename=item.source_filename,
        imported_at=item.imported_at,
        valid_operation_count=item.valid_operation_count,
        quarantined_row_count=item.quarantined_row_count,
        ignored_blank_row_count=item.ignored_blank_row_count,
    )


def _unresolved_data_quality_issue_response(
    item: UnresolvedDataQualityIssue,
) -> UnresolvedDataQualityIssueResponse:
    return UnresolvedDataQualityIssueResponse(
        dataset_version_id=item.dataset_version_id,
        source_filename=item.source_filename,
        sheet_name=item.sheet_name,
        row_number=item.row_number,
        messages=list(item.messages),
    )


def _missing_actual_prediction_response(
    item: MissingActualPrediction,
) -> MissingActualPredictionResponse:
    return MissingActualPredictionResponse(
        prediction_id=item.prediction_id,
        operation_id=item.operation_id,
        created_at=item.created_at,
        vehicle_category=item.vehicle_category,
    )


def _feature_drift_response(item: FeatureDriftSummary) -> FeatureDriftResponse:
    return FeatureDriftResponse(
        reference_row_count=item.reference_row_count,
        current_row_count=item.current_row_count,
        status=item.status,
        drift_share=item.drift_share,
        threshold=item.threshold,
        drifting_features=list(item.drifting_features),
    )


def _rolling_error_point_response(item: RollingErrorPoint) -> RollingErrorPointResponse:
    return RollingErrorPointResponse(
        observed_at=item.observed_at,
        matched_record_count=item.matched_record_count,
        mae_liters=item.mae_liters,
    )


def _category_degradation_response(item: CategoryDegradation) -> CategoryDegradationResponse:
    return CategoryDegradationResponse(
        vehicle_category=item.vehicle_category,
        matched_record_count=item.matched_record_count,
        rolling_mae_liters=item.rolling_mae_liters,
        threshold_liters=item.threshold_liters,
        degraded=item.degraded,
    )


def _monitoring_alert_response(item: MonitoringAlert) -> MonitoringAlertResponse:
    return MonitoringAlertResponse(
        alert_key=item.alert_key,
        kind=item.kind.value,
        severity=item.severity.value,
        message=item.message,
        details=item.details,
        first_observed_at=item.first_observed_at,
        last_observed_at=item.last_observed_at,
        resolved_at=item.resolved_at,
    )


def execute_create(
    request: CreateDailyOperationRequest, create_daily_operation: CreateDailyOperation
) -> DailyOperation:
    return create_daily_operation.execute(
        CreateDailyOperationCommand(
            vehicle_category=request.vehicle_category,
            activity_mode=request.activity_mode,
            lifting_hours=request.lifting_hours,
            total_distance_km=request.total_distance_km,
            distance_source=request.distance_source,
            stop_sequence=tuple(request.stop_sequence),
        )
    )


def _historical_dataset_import_response(
    result: HistoricalDatasetImportResult,
) -> HistoricalDatasetImportResponse:
    return HistoricalDatasetImportResponse(
        dataset_version=DatasetVersionResponse(
            dataset_version_id=result.dataset_version.dataset_version_id,
            version=result.dataset_version.version,
            source_filename=result.dataset_version.source_filename,
            valid_operation_count=result.dataset_version.valid_operation_count,
            quarantined_row_count=result.dataset_version.quarantined_row_count,
            ignored_blank_row_count=result.dataset_version.ignored_blank_row_count,
        ),
        valid_operations=[
            _historical_operation_response(operation) for operation in result.valid_operations
        ],
        correction_report=[
            DataQualityIssueResponse(
                sheet_name=issue.source.sheet_name,
                row_number=issue.source.row_number,
                reasons=[
                    CorrectionReasonResponse(field=reason.field, message=reason.message)
                    for reason in issue.reasons
                ],
                raw_values=issue.source.raw_values,
            )
            for issue in result.correction_report
        ],
    )


def _historical_operation_response(
    historical_operation: HistoricalDailyOperation,
) -> HistoricalDailyOperationResponse:
    operation = historical_operation.operation
    source = historical_operation.source
    return HistoricalDailyOperationResponse(
        vehicle_category=operation.vehicle_category,
        activity_mode=operation.activity_mode,
        lifting_hours=operation.lifting_hours,
        total_distance_km=operation.total_distance_km,
        distance_source=operation.distance_source,
        prepared_fuel_liters=historical_operation.prepared_fuel_liters,
        source=SourceProvenanceResponse(
            sheet_name=source.sheet_name,
            row_number=source.row_number,
            original_headers=source.original_headers,
            raw_values=source.raw_values,
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors = translate_validation_errors(error.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"errors": errors},
        )

    @app.exception_handler(DailyOperationValidationError)
    async def handle_daily_operation_validation(
        _request: Request, error: DailyOperationValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"errors": [{"field": error.field, "message": error.message}]},
        )

    @app.exception_handler(DailyOperationNotFoundError)
    async def handle_daily_operation_not_found(
        _request: Request, _error: DailyOperationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "operation_not_found",
                    "message": "Operasi harian tidak ditemukan.",
                }
            },
        )

    @app.exception_handler(DatasetVersionNotFoundError)
    async def handle_dataset_version_not_found(
        _request: Request, _error: DatasetVersionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "dataset_version_not_found",
                    "message": "Versi dataset tidak ditemukan.",
                }
            },
        )

    @app.exception_handler(HistoricalDatasetImportError)
    async def handle_historical_dataset_import(
        _request: Request, error: HistoricalDatasetImportError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"errors": [{"field": "file", "message": error.message}]},
        )

    @app.exception_handler(BaselineTrainingError)
    async def handle_baseline_training(
        _request: Request, error: BaselineTrainingError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"errors": [{"field": "dataset_version_id", "message": str(error)}]},
        )

    @app.exception_handler(BaselineModelNotFoundError)
    async def handle_baseline_not_found(
        _request: Request, _error: BaselineModelNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "baseline_model_not_found",
                    "message": "Belum ada kandidat baseline terlatih untuk membuat prediksi.",
                }
            },
        )

    @app.exception_handler(ActualFuelAlreadyRecordedError)
    async def handle_actual_fuel_already_recorded(
        _request: Request, _error: ActualFuelAlreadyRecordedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "actual_fuel_already_recorded",
                    "message": "Bahan bakar aktual untuk operasi ini sudah tercatat.",
                }
            },
        )

    @app.exception_handler(CandidateModelNotFoundError)
    async def handle_candidate_model_not_found(
        _request: Request, _error: CandidateModelNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "candidate_model_not_found",
                    "message": "Kandidat model tidak ditemukan atau bukan lagi kandidat.",
                }
            },
        )

    @app.exception_handler(ModelPromotionNotAllowedError)
    async def handle_model_promotion_not_allowed(
        _request: Request, error: ModelPromotionNotAllowedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": "model_promotion_not_allowed", "message": str(error)}},
        )


_FIELD_LABELS = {
    "file": "Berkas",
    "vehicle_category": "Kategori kendaraan",
    "activity_mode": "Mode aktivitas",
    "lifting_hours": "Jam lifting",
    "total_distance_km": "Jarak total",
    "distance_source": "Sumber jarak",
    "actual_fuel_liters": "Bahan bakar aktual",
    "measurement_source": "Sumber pengukuran",
}


def translate_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    return [_translate_validation_error(error) for error in errors]


def _translate_validation_error(error: Mapping[str, Any]) -> dict[str, str]:
    location = error.get("loc", ())
    field = str(location[-1]) if location else "request"
    label = _FIELD_LABELS.get(field, "Nilai")
    error_type = str(error.get("type", ""))

    if error_type == "missing":
        message = f"{label} wajib diisi."
    elif error_type in {"greater_than", "finite_number"} and field == "total_distance_km":
        message = "Jarak total harus lebih besar dari 0."
    elif error_type == "extra_forbidden":
        message = f"Kolom {field} tidak dikenali."
    elif error_type in {"enum", "literal_error"}:
        message = f"{label} tidak valid."
    elif error_type in {"float_parsing", "float_type"}:
        message = f"{label} harus berupa angka."
    else:
        message = f"{label} tidak valid."
    return {"field": field, "message": message}
