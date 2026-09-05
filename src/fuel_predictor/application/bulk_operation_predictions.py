from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fuel_predictor.application.baseline_predictions import GenerateFuelPrediction
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    CreateDailyOperationCommand,
)
from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetImportError,
    HistoricalDatasetSourceReader,
    is_blank,
    normalize_header,
    parse_activity_mode,
    parse_distance_source,
    parse_number,
    parse_vehicle,
    parse_vehicle_category,
)
from fuel_predictor.domain.daily_operation import DailyOperation, DailyOperationValidationError
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

    def execute(self, source_filename: str, content: bytes) -> BulkOperationPredictionResult:
        if not content:
            raise HistoricalDatasetImportError("Berkas impor kosong.")

        # Check before creating any operation, so a missing candidate cannot leave orphan rows.
        self._generate_fuel_prediction.ensure_model_available()
        accepted_rows: list[BulkPredictionAcceptedRow] = []
        issues: list[DataQualityIssue] = []
        ignored_blank_row_count = 0
        for sheet in self._source_reader.read(source_filename, content):
            mapped_headers = _map_headers(sheet.headers)
            for row_number, values in sheet.rows:
                raw_values = dict(zip(sheet.headers, values, strict=True))
                if _is_blank_row(raw_values, mapped_headers):
                    ignored_blank_row_count += 1
                    continue
                source = SourceProvenance(
                    source_filename=source_filename,
                    sheet_name=sheet.name,
                    row_number=row_number,
                    original_headers=dict(mapped_headers),
                    raw_values=raw_values,
                )
                command, row_issues = _command_for_row(mapped_headers, raw_values)
                if row_issues:
                    issues.append(DataQualityIssue(source=source, reasons=tuple(row_issues)))
                    continue

                assert command is not None
                try:
                    operation = self._create_daily_operation.execute(command)
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

        return BulkOperationPredictionResult(
            accepted_rows=tuple(accepted_rows),
            correction_report=tuple(issues),
            ignored_blank_row_count=ignored_blank_row_count,
        )


_HEADER_ALIASES = {
    "vehicle_category": {"kategori angber", "kategori angber wajib", "angber"},
    "activity_mode": {"mode aktivitas", "mode aktivitas wajib", "aktivitas"},
    "lifting_hours": {"jam lifting", "jam lifting opsional", "jam operasi lifting"},
    "total_distance_km": {
        "jarak total km",
        "jarak total km wajib",
        "jarak total",
    },
    "vehicle": {"kendaraan", "unit", "unit kendaraan", "nama kendaraan", "armada", "vehicle"},
    "distance_source": {"sumber jarak", "sumber jarak wajib"},
    "stop_sequence": {"urutan pemberhentian", "urutan pemberhentian opsional"},
}
_REQUIRED_FIELDS = {
    "vehicle_category",
    "activity_mode",
    "total_distance_km",
    "distance_source",
}
_FIELD_LABELS = {
    "vehicle_category": "Kategori kendaraan",
    "vehicle": "Kendaraan",
    "activity_mode": "Mode aktivitas",
    "lifting_hours": "Jam lifting",
    "total_distance_km": "Jarak total",
    "distance_source": "Sumber jarak",
    "stop_sequence": "Urutan pemberhentian",
}


def _map_headers(headers: Sequence[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for header in headers:
        normalized = normalize_header(header)
        for field, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                mapped.setdefault(field, header)
    return mapped


def _is_blank_row(raw_values: dict[str, RawValue], mapped_headers: dict[str, str]) -> bool:
    operation_headers = tuple(mapped_headers.values())
    if operation_headers:
        return all(is_blank(raw_values[header]) for header in operation_headers)
    return all(is_blank(value) for value in raw_values.values())


def _command_for_row(
    mapped_headers: dict[str, str], raw_values: dict[str, RawValue]
) -> tuple[CreateDailyOperationCommand | None, list[CorrectionReason]]:
    issues: list[CorrectionReason] = []
    raw_by_field: dict[str, RawValue] = {}
    for field in _REQUIRED_FIELDS | {"lifting_hours", "stop_sequence", "vehicle"}:
        header = mapped_headers.get(field)
        if header is None:
            if field in _REQUIRED_FIELDS:
                issues.append(
                    CorrectionReason(field, f"Kolom {_FIELD_LABELS[field]} tidak ditemukan.")
                )
        else:
            raw_by_field[field] = raw_values[header]

    vehicle_category = (
        parse_vehicle_category(raw_by_field["vehicle_category"], issues)
        if "vehicle_category" in raw_by_field
        else None
    )
    vehicle = parse_vehicle(raw_by_field.get("vehicle"), issues)
    activity_mode = (
        parse_activity_mode(raw_by_field["activity_mode"], issues)
        if "activity_mode" in raw_by_field
        else None
    )
    lifting_hours = parse_number(raw_by_field.get("lifting_hours"), "lifting_hours", issues)
    total_distance_km = (
        parse_number(raw_by_field["total_distance_km"], "total_distance_km", issues, required=True)
        if "total_distance_km" in raw_by_field
        else None
    )
    distance_source = (
        parse_distance_source(raw_by_field["distance_source"], issues)
        if "distance_source" in raw_by_field
        else None
    )
    stop_sequence = _parse_stop_sequence(raw_by_field.get("stop_sequence"), issues)

    if total_distance_km is not None and total_distance_km <= 0:
        issues.append(
            CorrectionReason("total_distance_km", "Jarak total harus lebih besar dari 0.")
        )
    if issues:
        return None, issues

    assert vehicle_category is not None
    assert activity_mode is not None
    assert total_distance_km is not None
    assert distance_source is not None
    try:
        DailyOperation(
            operation_id="BULK-ROW-VALIDATION",
            vehicle_category=vehicle_category,
            vehicle=vehicle,
            activity_mode=activity_mode,
            lifting_hours=lifting_hours,
            total_distance_km=total_distance_km,
            distance_source=distance_source,
            stop_sequence=stop_sequence,
        )
    except DailyOperationValidationError as error:
        return None, [CorrectionReason(error.field, error.message)]
    return (
        CreateDailyOperationCommand(
            vehicle_category=vehicle_category,
            vehicle=vehicle,
            activity_mode=activity_mode,
            lifting_hours=lifting_hours,
            total_distance_km=total_distance_km,
            distance_source=distance_source,
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
