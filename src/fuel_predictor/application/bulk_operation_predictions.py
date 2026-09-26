from dataclasses import dataclass, replace
from typing import Protocol

from fuel_predictor.application.baseline_predictions import GenerateFuelPrediction
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    CreateDailyOperationCommand,
)
from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetImportError,
    HistoricalDatasetSourceReader,
    SheetRows,
    is_blank,
    pick_columns,
    read_operation_columns,
)
from fuel_predictor.domain.daily_operation import (
    DailyOperation,
    DailyOperationValidationError,
)
from fuel_predictor.domain.historical_dataset import (
    CorrectionReason,
    DataQualityIssue,
    RawValue,
    SourceProvenance,
)
from fuel_predictor.domain.prediction import FuelPrediction


class BulkOperationSourceWriter(Protocol):
    def add_source(self, operation_id: str, source: SourceProvenance) -> None: ...


@dataclass(frozen=True, slots=True)
class BulkPredictionAcceptedRow:
    source: SourceProvenance
    operation: DailyOperation
    prediction: FuelPrediction


@dataclass(frozen=True, slots=True)
class BulkOperationPredictionResult:
    accepted_rows: tuple[BulkPredictionAcceptedRow, ...]
    correction_report: tuple[DataQualityIssue, ...]
    ignored_blank_row_count: int


class BulkOperationPrediction:
    """Run spreadsheet rows through the same operation and prediction use cases as the API."""

    def __init__(
        self,
        source_reader: HistoricalDatasetSourceReader,
        create_daily_operation: CreateDailyOperation,
        generate_fuel_prediction: GenerateFuelPrediction,
        source_writer: BulkOperationSourceWriter,
    ) -> None:
        self._source_reader = source_reader
        self._create_daily_operation = create_daily_operation
        self._generate_fuel_prediction = generate_fuel_prediction
        self._source_writer = source_writer

    def execute(
        self, source_filename: str, content: bytes, *, actor: str | None = None
    ) -> BulkOperationPredictionResult:
        if not content:
            raise HistoricalDatasetImportError("Berkas impor kosong.")

        # Check before creating any operation, so a missing candidate cannot leave orphan rows.
        self._generate_fuel_prediction.ensure_model_available()
        accepted_rows: list[BulkPredictionAcceptedRow] = []
        issues: list[DataQualityIssue] = []
        rows = SheetRows(_HEADER_ALIASES)
        for row in rows.read(self._source_reader.read(source_filename, content)):
            source = SourceProvenance(
                source_filename=source_filename,
                sheet_name=row.sheet_name,
                row_number=row.row_number,
                original_headers=dict(row.mapped_headers),
                raw_values=row.raw_values,
            )
            # The unit is resolved to its fleet name by CreateDailyOperation, as
            # for every plan; a unit the fleet does not know is planned as written.
            command, row_issues = _command_for_row(row.mapped_headers, row.raw_values)
            if row_issues:
                issues.append(DataQualityIssue(source=source, reasons=tuple(row_issues)))
                continue

            assert command is not None
            try:
                operation = self._create_daily_operation.execute(
                    replace(command, created_by=actor)
                )
            except DailyOperationValidationError as error:
                issues.append(
                    DataQualityIssue(
                        source=source,
                        reasons=(CorrectionReason(error.field, error.message),),
                    )
                )
                continue
            self._source_writer.add_source(operation.operation_id, source)
            prediction = self._generate_fuel_prediction.execute(operation.operation_id)
            accepted_rows.append(BulkPredictionAcceptedRow(source, operation, prediction))
        ignored_blank_row_count = rows.blank_row_count
        return BulkOperationPredictionResult(
            accepted_rows=tuple(accepted_rows),
            correction_report=tuple(issues),
            ignored_blank_row_count=ignored_blank_row_count,
        )


_HEADER_ALIASES = {
    "vehicle_category": {"kategori angber", "kategori angber wajib", "angber"},
    "activity_mode": {"mode aktivitas", "mode aktivitas wajib", "aktivitas", "aktivitas wajib"},
    "lifting_hours": {"jam lifting", "jam lifting opsional", "jam operasi lifting"},
    "total_distance_km": {
        "jarak total km",
        "jarak total km wajib",
        "jarak total",
    },
    # "kendaraan opsional" is the template's own header, "Kendaraan (opsional)";
    # without it every sheet filled from the template lost its vehicles.
    "vehicle": {
        "kendaraan",
        "kendaraan opsional",
        "unit",
        "unit kendaraan",
        "nama kendaraan",
        "armada",
        "vehicle",
    },
    "distance_source": {"sumber jarak", "sumber jarak wajib"},
    "stop_sequence": {"urutan pemberhentian", "urutan pemberhentian opsional"},
}
_REQUIRED_FIELDS = {"activity_mode", "total_distance_km"}
# Asked by older templates only: every unit is ANGBER, and a distance typed
# into the sheet is a manual one. When present they are still read.
_DEFAULTED_FIELDS = {"vehicle_category", "distance_source"}
_FIELD_LABELS = {
    "vehicle_category": "Kategori kendaraan",
    "vehicle": "Kendaraan",
    "activity_mode": "Aktivitas",
    "lifting_hours": "Jam lifting",
    "total_distance_km": "Jarak total",
    "distance_source": "Sumber jarak",
    "stop_sequence": "Urutan pemberhentian",
}


def _command_for_row(
    mapped_headers: dict[str, str],
    raw_values: dict[str, RawValue],
) -> tuple[CreateDailyOperationCommand | None, list[CorrectionReason]]:
    issues: list[CorrectionReason] = []
    raw_by_field = pick_columns(
        mapped_headers,
        raw_values,
        _REQUIRED_FIELDS | _DEFAULTED_FIELDS | {"lifting_hours", "stop_sequence", "vehicle"},
        _REQUIRED_FIELDS,
        _FIELD_LABELS,
        issues,
    )
    columns = read_operation_columns(raw_by_field, issues)
    stop_sequence = _parse_stop_sequence(raw_by_field.get("stop_sequence"), issues)
    if issues or columns is None:
        return None, issues
    try:
        # Built only to be checked the way a planned operation is; the
        # command is what creates it.
        DailyOperation(
            operation_id="BULK-ROW-VALIDATION",
            vehicle_category=columns.vehicle_category,
            vehicle=columns.vehicle,
            activity_mode=columns.activity_mode,
            lifting_hours=columns.lifting_hours,
            total_distance_km=columns.total_distance_km,
            distance_source=columns.distance_source,
            stop_sequence=stop_sequence,
        )
    except DailyOperationValidationError as error:
        return None, [CorrectionReason(error.field, error.message)]
    return (
        CreateDailyOperationCommand(
            vehicle_category=columns.vehicle_category,
            vehicle=columns.vehicle,
            activity_mode=columns.activity_mode,
            lifting_hours=columns.lifting_hours,
            total_distance_km=columns.total_distance_km,
            distance_source=columns.distance_source,
            stop_sequence=stop_sequence,
        ),
        [],
    )


def _parse_stop_sequence(
    raw_value: RawValue | None, issues: list[CorrectionReason]
) -> tuple[str, ...]:
    if is_blank(raw_value):
        return ()
    stops = tuple(part.strip() for part in str(raw_value).split(">"))
    if len(stops) < 2:
        issues.append(
            CorrectionReason(
                "stop_sequence",
                "Urutan pemberhentian harus berisi setidaknya dua lokasi yang dipisahkan dengan >.",
            )
        )
    elif any(not stop for stop in stops):
        issues.append(
            CorrectionReason(
                "stop_sequence",
                "Nama setiap pemberhentian wajib diisi; gunakan > di antara lokasi.",
            )
        )
    return stops
