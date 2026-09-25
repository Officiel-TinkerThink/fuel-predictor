import re
from dataclasses import dataclass, replace
from math import isfinite

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    RecordActualFuel,
    RecordActualFuelCommand,
)
from fuel_predictor.application.daily_operations import (
    DailyOperationNotFoundError,
    OperationCancelledError,
)
from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetImportError,
    HistoricalDatasetSourceReader,
    is_blank,
    normalize_header,
)
from fuel_predictor.application.wording import liters
from fuel_predictor.domain.actual_fuel import ActualFuelMeasurementSource, ActualFuelRecord
from fuel_predictor.domain.historical_dataset import (
    CorrectionReason,
    DataQualityIssue,
    RawValue,
    SourceProvenance,
)


@dataclass(frozen=True, slots=True)
class BulkActualFuelAcceptedRow:
    source: SourceProvenance
    actual_fuel: ActualFuelRecord
    # How the operator knows the operation; None only for imported history.
    operation_code: str | None = None


@dataclass(frozen=True, slots=True)
class BulkActualFuelResult:
    accepted_rows: tuple[BulkActualFuelAcceptedRow, ...]
    correction_report: tuple[DataQualityIssue, ...]
    ignored_blank_row_count: int
    # Rows naming an operation but no litres yet: a sheet of waiting operations
    # is filled in over days, and the rows not done yet are not mistakes.
    unfilled_row_count: int = 0
    # Rows whose figure is already on record: the same sheet uploaded again
    # after more rows were filled. Nothing to do, and not a mistake either.
    already_recorded_row_count: int = 0


class BulkActualFuel:
    def __init__(
        self,
        source_reader: HistoricalDatasetSourceReader,
        record_actual_fuel: RecordActualFuel,
    ) -> None:
        self._source_reader = source_reader
        self._record_actual_fuel = record_actual_fuel

    def execute(
        self, source_filename: str, content: bytes, *, actor: str | None = None
    ) -> BulkActualFuelResult:
        if not content:
            raise HistoricalDatasetImportError("Berkas impor kosong.")

        accepted_rows: list[BulkActualFuelAcceptedRow] = []
        issues: list[DataQualityIssue] = []
        ignored_blank_row_count = 0
        unfilled_row_count = 0
        already_recorded_row_count = 0
        data_sheets = 0
        for sheet in self._source_reader.read(source_filename, content):
            mapped_headers = _map_headers(sheet.headers)
            # A sheet with none of the columns - a template's instructions -
            # is not data; reading it quarantined every instruction line.
            if not mapped_headers:
                continue
            data_sheets += 1
            for row_number, values in sheet.rows:
                raw_values = dict(zip(sheet.headers, values, strict=True))
                if _is_blank_row(raw_values, mapped_headers):
                    ignored_blank_row_count += 1
                    continue
                if _is_unfilled_row(raw_values, mapped_headers):
                    unfilled_row_count += 1
                    continue
                source = SourceProvenance(
                    source_filename=source_filename,
                    sheet_name=sheet.name,
                    row_number=row_number,
                    original_headers=dict(mapped_headers),
                    raw_values=raw_values,
                )
                command, row_issues = _command_for_row(mapped_headers, raw_values, source)
                if row_issues:
                    issues.append(DataQualityIssue(source, tuple(row_issues)))
                    continue
                assert command is not None
                try:
                    record = self._record_actual_fuel.execute(replace(command, recorded_by=actor))
                except DailyOperationNotFoundError:
                    issues.append(
                        DataQualityIssue(
                            source,
                            (CorrectionReason("operation_id", "Kode operasi tidak ditemukan."),),
                        )
                    )
                except OperationCancelledError:
                    issues.append(
                        DataQualityIssue(
                            source,
                            (CorrectionReason("operation_id", "Operasi ini sudah dibatalkan."),),
                        )
                    )
                except ActualFuelAlreadyRecordedError as error:
                    if error.repeats(command.actual_fuel_liters):
                        already_recorded_row_count += 1
                        continue
                    issues.append(
                        DataQualityIssue(
                            source,
                            (CorrectionReason("actual_fuel_liters", _conflict(error, command)),),
                        )
                    )
                else:
                    accepted_rows.append(
                        BulkActualFuelAcceptedRow(
                            source, record, self._record_actual_fuel.code_for(record)
                        )
                    )
        if data_sheets == 0:
            raise HistoricalDatasetImportError(
                "Berkas tidak memuat satu pun kolom yang dikenali. "
                "Gunakan template dari halaman ini."
            )
        return BulkActualFuelResult(
            accepted_rows=tuple(accepted_rows),
            correction_report=tuple(issues),
            ignored_blank_row_count=ignored_blank_row_count,
            unfilled_row_count=unfilled_row_count,
            already_recorded_row_count=already_recorded_row_count,
        )


def _conflict(error: ActualFuelAlreadyRecordedError, command: RecordActualFuelCommand) -> str:
    if error.recorded_liters is None:
        return "Bahan bakar aktual untuk operasi ini sudah tercatat."
    return (
        f"Sudah tercatat {liters(error.recorded_liters)}, berbeda dengan "
        f"{liters(command.actual_fuel_liters)} di berkas. Angka yang sudah tercatat "
        "tidak diubah lewat impor."
    )


_HEADER_ALIASES = {
    # "ID Operasi" is what the template said before operation codes (ADR 0016);
    # sheets filled in from it still import.
    "operation_id": {
        "kode operasi",
        "kode operasi wajib",
        "kode",
        "id operasi",
        "id operasi wajib",
        "operation code",
        "operation id",
        "operation_id",
    },
    "actual_fuel_liters": {
        "bahan bakar aktual l",
        "bahan bakar aktual l wajib",
        "bahan bakar aktual",
        "actual fuel liters",
        "actual fuel l",
    },
    "measurement_source": {
        "sumber pengukuran",
        "sumber pengukuran opsional",
        "measurement source",
        "sumber aktual",
    },
}


def _map_headers(headers: tuple[str, ...]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for header in headers:
        normalized = normalize_header(header)
        for field, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                mapped.setdefault(field, header)
    return mapped


def _is_blank_row(raw_values: dict[str, RawValue], mapped_headers: dict[str, str]) -> bool:
    relevant_headers = tuple(mapped_headers.values())
    if relevant_headers:
        return all(is_blank(raw_values[header]) for header in relevant_headers)
    return all(is_blank(value) for value in raw_values.values())


def _is_unfilled_row(raw_values: dict[str, RawValue], mapped_headers: dict[str, str]) -> bool:
    """An operation named, its litres not written yet."""
    code_header = mapped_headers.get("operation_id")
    litres_header = mapped_headers.get("actual_fuel_liters")
    if code_header is None or litres_header is None:
        return False
    return not is_blank(raw_values[code_header]) and is_blank(raw_values[litres_header])


def _command_for_row(
    mapped_headers: dict[str, str], raw_values: dict[str, RawValue], source: SourceProvenance
) -> tuple[RecordActualFuelCommand | None, list[CorrectionReason]]:
    issues: list[CorrectionReason] = []
    operation_header = mapped_headers.get("operation_id")
    actual_fuel_header = mapped_headers.get("actual_fuel_liters")
    if operation_header is None:
        issues.append(CorrectionReason("operation_id", "Kolom Kode operasi tidak ditemukan."))
    if actual_fuel_header is None:
        issues.append(
            CorrectionReason("actual_fuel_liters", "Kolom Bahan bakar aktual tidak ditemukan.")
        )
    if issues:
        return None, issues

    assert operation_header is not None
    assert actual_fuel_header is not None
    raw_operation_id = raw_values[operation_header]
    operation_id = str(raw_operation_id).strip() if not is_blank(raw_operation_id) else ""
    if not operation_id:
        issues.append(CorrectionReason("operation_id", "Kode operasi wajib diisi."))
    actual_fuel = _parse_actual_fuel(raw_values[actual_fuel_header], issues)
    if actual_fuel is not None and actual_fuel <= 0:
        issues.append(
            CorrectionReason("actual_fuel_liters", "Bahan bakar aktual harus lebih besar dari 0.")
        )
    measurement_source = _parse_measurement_source(
        raw_values.get(mapped_headers.get("measurement_source", "")), issues
    )
    if issues:
        return None, issues
    assert actual_fuel is not None
    assert measurement_source is not None
    return (
        RecordActualFuelCommand(
            operation_reference=operation_id,
            actual_fuel_liters=actual_fuel,
            measurement_source=measurement_source,
            source_filename=source.source_filename,
            source_sheet_name=source.sheet_name,
            source_row_number=source.row_number,
        ),
        [],
    )


def _parse_measurement_source(
    raw_value: RawValue | None, issues: list[CorrectionReason]
) -> ActualFuelMeasurementSource | None:
    if is_blank(raw_value):
        return ActualFuelMeasurementSource.SPREADSHEET_IMPORT
    aliases = {
        "manual entry": ActualFuelMeasurementSource.MANUAL_ENTRY,
        "manual": ActualFuelMeasurementSource.MANUAL_ENTRY,
        "fuel meter": ActualFuelMeasurementSource.FUEL_METER,
        "meter bbm": ActualFuelMeasurementSource.FUEL_METER,
        "receipt": ActualFuelMeasurementSource.RECEIPT,
        "bukti": ActualFuelMeasurementSource.RECEIPT,
        "spreadsheet import": ActualFuelMeasurementSource.SPREADSHEET_IMPORT,
    }
    source = aliases.get(normalize_header(str(raw_value)))
    if source is None:
        issues.append(CorrectionReason("measurement_source", "Sumber pengukuran tidak valid."))
    return source


def _parse_actual_fuel(raw_value: RawValue, issues: list[CorrectionReason]) -> float | None:
    if is_blank(raw_value):
        issues.append(CorrectionReason("actual_fuel_liters", "Bahan bakar aktual wajib diisi."))
        return None
    if isinstance(raw_value, bool):
        issues.append(
            CorrectionReason("actual_fuel_liters", "Bahan bakar aktual harus berupa angka.")
        )
        return None
    if isinstance(raw_value, str):
        normalized = raw_value.strip()
        if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", normalized):
            issues.append(
                CorrectionReason("actual_fuel_liters", "Bahan bakar aktual harus berupa angka.")
            )
            return None
        value = float(normalized.replace(",", "."))
    else:
        assert raw_value is not None
        value = float(raw_value)
    if not isfinite(value):
        issues.append(
            CorrectionReason("actual_fuel_liters", "Bahan bakar aktual harus berupa angka.")
        )
        return None
    return value
