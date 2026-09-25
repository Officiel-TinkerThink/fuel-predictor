"""The important events a page or API call records in the audit trail.

The trail is for what an administrator would want to reconstruct later - an
operation planned, an actual reported, a file imported, a model changed -
not for traffic. Each helper names the event once so every entry point
(page, JSON API, bulk import) writes the same record with the same details.
"""

from fuel_predictor.application.bulk_actual_fuel import BulkActualFuelResult
from fuel_predictor.application.bulk_operation_predictions import BulkOperationPredictionResult
from fuel_predictor.application.identity import RecordAuditEvent
from fuel_predictor.domain.actual_fuel import ActualFuelRecord
from fuel_predictor.domain.daily_operation import DailyOperation
from fuel_predictor.domain.historical_dataset import DatasetVersion
from fuel_predictor.domain.identity import AuditOutcome
from fuel_predictor.domain.prediction import FuelPrediction, ModelVersion

Details = dict[str, str | int | float | bool | None]


class ImportantEvents:
    def __init__(self, record_audit: RecordAuditEvent) -> None:
        self._record = record_audit

    def operation_planned(
        self, actor: str | None, operation: DailyOperation, prediction: FuelPrediction | None
    ) -> None:
        # Enough to recognise the row; the operation's own page has the rest.
        details: Details = {
            "kode": operation.operation_code,
            "vehicle": operation.vehicle,
            "jarak_km": round(operation.total_distance_km, 1),
        }
        if prediction is not None:
            details["liters"] = round(prediction.recommended_allocation_liters, 1)
        self._note(actor, "operation_planned", operation.operation_id, details)

    def operation_cancelled(self, actor: str | None, operation: DailyOperation) -> None:
        self._note(
            actor,
            "operation_cancelled",
            operation.operation_id,
            {"kode": operation.operation_code, "reason": operation.cancel_reason},
        )

    def actual_fuel_recorded(
        self, actor: str | None, record: ActualFuelRecord, code: str | None = None
    ) -> None:
        self._note(
            actor,
            "actual_fuel_recorded",
            record.operation_id,
            {
                "kode": code,
                "liters": record.actual_fuel_liters,
                "source": record.measurement_source.value,
            },
        )

    def bulk_prediction_imported(
        self, actor: str | None, filename: str, result: BulkOperationPredictionResult
    ) -> None:
        self._note(
            actor,
            "bulk_prediction_imported",
            filename,
            {
                "accepted": len(result.accepted_rows),
                "quarantined": len(result.correction_report),
            },
        )

    def bulk_actual_imported(
        self, actor: str | None, filename: str, result: BulkActualFuelResult
    ) -> None:
        self._note(
            actor,
            "bulk_actual_imported",
            filename,
            {
                "accepted": len(result.accepted_rows),
                "quarantined": len(result.correction_report),
            },
        )

    def historical_dataset_imported(self, actor: str | None, dataset: DatasetVersion) -> None:
        self._note(
            actor,
            "historical_dataset_imported",
            dataset.dataset_version_id,
            {
                "file": dataset.source_filename,
                "valid": dataset.valid_operation_count,
                "quarantined": dataset.quarantined_row_count,
            },
        )

    def model_candidate_trained(self, actor: str | None, model: ModelVersion) -> None:
        self._note(
            actor,
            "model_candidate_trained",
            model.model_version_id,
            {"dataset": model.dataset_version_id, "rows": model.training_row_count},
        )

    def model_promoted(
        self, actor: str | None, model: ModelVersion, previous: str | None = None
    ) -> None:
        self._note(actor, "model_promoted", model.model_version_id, {"previous": previous})

    def model_package_uploaded(
        self, actor: str | None, filename: str, model_version: str | None, accepted: bool
    ) -> None:
        self._record.execute(
            actor=actor or "sistem",
            action="model_package_uploaded",
            outcome=AuditOutcome.SUCCEEDED if accepted else AuditOutcome.FAILED,
            subject=model_version or filename,
            details={"file": filename},
        )

    def _note(self, actor: str | None, action: str, subject: str, details: Details) -> None:
        self._record.execute(
            actor=actor or "sistem",
            action=action,
            outcome=AuditOutcome.SUCCEEDED,
            subject=subject,
            details={key: value for key, value in details.items() if value is not None},
        )
