import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from uuid import uuid4

from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DailyOperationValidationError,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.historical_dataset import (
    CorrectionReason,
    DataQualityIssue,
    DatasetVersion,
    HistoricalDailyOperation,
    RawValue,
    SourceProvenance,
)


@dataclass(frozen=True, slots=True)
class SourceSheet:
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[int, tuple[RawValue, ...]], ...]


class HistoricalDatasetSourceReader(Protocol):
    def read(self, filename: str, content: bytes) -> Sequence[SourceSheet]: ...


class HistoricalDatasetWriter(Protocol):
    def create(
        self,
        source_filename: str,
        valid_operations: Sequence[HistoricalDailyOperation],
        issues: Sequence[DataQualityIssue],
        ignored_blank_row_count: int,
    ) -> DatasetVersion: ...


class HistoricalDatasetReader(Protocol):
    def get_valid_operations(
        self, dataset_version_id: str
    ) -> Sequence[HistoricalDailyOperation] | None: ...


class DatasetVersionNotFoundError(LookupError):
    pass


class HistoricalDatasetImportError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class HistoricalDatasetImportResult:
    dataset_version: DatasetVersion
    valid_operations: tuple[HistoricalDailyOperation, ...]
    correction_report: tuple[DataQualityIssue, ...]


class ImportHistoricalDataset:
    def __init__(
        self,
        source_reader: HistoricalDatasetSourceReader,
        repository: HistoricalDatasetWriter,
        operation_id_factory: Callable[[], str] | None = None,
        vehicle_catalog: VehicleCatalog | None = None,
    ) -> None:
        self._source_reader = source_reader
        self._repository = repository
        self._operation_id_factory = operation_id_factory or _new_imported_operation_id
        # Without a catalog the written name is taken as-is, which keeps the
        # importer usable on its own; with one, "PM 01" resolves to Prime Mover
        # rather than becoming a second vehicle.
        self._vehicle_catalog = vehicle_catalog

    def execute(self, source_filename: str, content: bytes) -> HistoricalDatasetImportResult:
        if not content:
            raise HistoricalDatasetImportError("Berkas impor kosong.")

        valid_operations: list[HistoricalDailyOperation] = []
        issues: list[DataQualityIssue] = []
        ignored_blank_row_count = 0
        for sheet in self._source_reader.read(source_filename, content):
            mapped_headers = _map_headers(sheet.headers)
            for row_number, values in sheet.rows:
                raw_values = dict(zip(sheet.headers, values, strict=True))
                if _is_blank_calendar_row(raw_values, mapped_headers):
                    ignored_blank_row_count += 1
                    continue

                provenance = SourceProvenance(
                    sheet_name=sheet.name,
                    row_number=row_number,
                    original_headers=_lifting_header_provenance(mapped_headers),
                    raw_values=raw_values,
                    source_filename=source_filename,
                )
                operation, row_issues = _validate_row(
                    mapped_headers,
                    raw_values,
                    provenance,
                    self._operation_id_factory,
                    self._vehicle_catalog,
                )
                if row_issues:
                    issues.append(DataQualityIssue(source=provenance, reasons=tuple(row_issues)))
                elif operation is not None:
                    valid_operations.append(operation)

        dataset_version = self._repository.create(
            source_filename=source_filename,
            valid_operations=valid_operations,
            issues=issues,
            ignored_blank_row_count=ignored_blank_row_count,
        )
        return HistoricalDatasetImportResult(
            dataset_version=dataset_version,
            valid_operations=tuple(valid_operations),
            correction_report=tuple(issues),
        )


class GetDatasetValidOperations:
    def __init__(self, repository: HistoricalDatasetReader) -> None:
        self._repository = repository

    def execute(self, dataset_version_id: str) -> tuple[HistoricalDailyOperation, ...]:
        operations = self._repository.get_valid_operations(dataset_version_id)
        if operations is None:
            raise DatasetVersionNotFoundError(dataset_version_id)
        return tuple(operations)


_HEADER_ALIASES = {
    "vehicle_category": {"kategori angber", "kategori kendaraan", "jenis kendaraan", "angber"},
    "vehicle": {"kendaraan", "unit", "unit kendaraan", "nama kendaraan", "armada", "vehicle"},
    "activity_mode": {"mode aktivitas", "aktivitas", "jenis aktivitas"},
    "lifting_hours": {"jam lifting", "jam operasi lifting", "lifting hours", "lifting hour"},
    "total_distance_km": {"jarak total km", "jarak total", "total distance km"},
    "prepared_fuel_liters": {
        "bahan bakar disiapkan l",
        "bahan bakar disiapkan",
        "prepared fuel liters",
        "prepared fuel l",
    },
    "distance_source": {"sumber jarak", "distance source"},
}
_REQUIRED_FIELDS = {
    "vehicle_category",
    "activity_mode",
    "total_distance_km",
    "prepared_fuel_liters",
    "distance_source",
}
_FIELD_LABELS = {
    "vehicle_category": "Kategori kendaraan",
    "vehicle": "Kendaraan",
    "activity_mode": "Mode aktivitas",
    "lifting_hours": "Jam lifting",
    "total_distance_km": "Jarak total",
    "prepared_fuel_liters": "Bahan bakar disiapkan",
    "distance_source": "Sumber jarak",
}


def _map_headers(headers: tuple[str, ...]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for header in headers:
        normalized = normalize_header(header)
        for field, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                mapped.setdefault(field, header)
    return mapped


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _lifting_header_provenance(mapped_headers: dict[str, str]) -> dict[str, str]:
    header = mapped_headers.get("lifting_hours")
    return {"lifting_hours": header} if header is not None else {}


def _is_blank_calendar_row(raw_values: dict[str, RawValue], mapped_headers: dict[str, str]) -> bool:
    operation_headers = tuple(mapped_headers.values())
    if operation_headers:
        return all(is_blank(raw_values[header]) for header in operation_headers)
    return all(is_blank(value) for value in raw_values.values())


def is_blank(value: RawValue) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _validate_row(
    mapped_headers: dict[str, str],
    raw_values: dict[str, RawValue],
    provenance: SourceProvenance,
    operation_id_factory: Callable[[], str],
    vehicle_catalog: VehicleCatalog | None = None,
) -> tuple[HistoricalDailyOperation | None, list[CorrectionReason]]:
    issues: list[CorrectionReason] = []
    raw_by_field: dict[str, RawValue] = {}
    for field in _REQUIRED_FIELDS | {"lifting_hours", "vehicle"}:
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
    vehicle = parse_vehicle(raw_by_field.get("vehicle"), issues, vehicle_catalog)
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
    prepared_fuel_liters = (
        parse_number(
            raw_by_field["prepared_fuel_liters"], "prepared_fuel_liters", issues, required=True
        )
        if "prepared_fuel_liters" in raw_by_field
        else None
    )
    distance_source = (
        parse_distance_source(raw_by_field["distance_source"], issues)
        if "distance_source" in raw_by_field
        else None
    )

    if total_distance_km is not None and total_distance_km <= 0:
        issues.append(
            CorrectionReason("total_distance_km", "Jarak total harus lebih besar dari 0.")
        )
    if prepared_fuel_liters is not None and prepared_fuel_liters <= 0:
        issues.append(
            CorrectionReason(
                "prepared_fuel_liters", "Bahan bakar disiapkan harus lebih besar dari 0."
            )
        )
    if issues:
        return None, issues

    assert vehicle_category is not None
    assert activity_mode is not None
    assert total_distance_km is not None
    assert prepared_fuel_liters is not None
    assert distance_source is not None
    try:
        operation = DailyOperation(
            operation_id=operation_id_factory(),
            vehicle_category=vehicle_category,
            vehicle=vehicle,
            activity_mode=activity_mode,
            lifting_hours=lifting_hours,
            total_distance_km=total_distance_km,
            distance_source=distance_source,
        )
    except DailyOperationValidationError as error:
        return None, [CorrectionReason(error.field, error.message)]
    return HistoricalDailyOperation(operation, prepared_fuel_liters, provenance), []


def parse_vehicle(
    raw_value: RawValue | None,
    issues: list[CorrectionReason],
    catalog: VehicleCatalog | None = None,
) -> str | None:
    """Optional: a sheet that never named the unit still imports, and those rows
    simply teach the model nothing about individual vehicles.

    A catalogued name is returned in its canonical spelling, so history written
    as "PM 01", "T CRANE 01" or "WHELL CRANE" lands on one vehicle rather than
    fragmenting the feature across the ways people write it.
    """
    if is_blank(raw_value):
        return None
    written = str(raw_value).strip()
    known = catalog.options() if catalog is not None else ()
    if not known:
        # No catalog, or one not imported yet: take the name as written rather
        # than quarantining every row on a database where the fleet has not
        # been loaded.
        return written
    assert catalog is not None
    match = catalog.find(written)
    if match is None:
        valid = ", ".join(option.name for option in known)
        issues.append(
            CorrectionReason("vehicle", f"Kendaraan tidak dikenali. Gunakan salah satu: {valid}.")
        )
        return None
    return match.name


def parse_vehicle_category(
    raw_value: RawValue | None, issues: list[CorrectionReason]
) -> VehicleCategory | None:
    if is_blank(raw_value):
        issues.append(CorrectionReason("vehicle_category", "Kategori kendaraan wajib diisi."))
        return None
    value = normalized_value(raw_value)
    if value in {"angber", "angkutan berat"}:
        return VehicleCategory.ANGBER
    issues.append(CorrectionReason("vehicle_category", "Kategori kendaraan ANGBER tidak dikenali."))
    return None


def parse_activity_mode(
    raw_value: RawValue | None, issues: list[CorrectionReason]
) -> ActivityMode | None:
    if is_blank(raw_value):
        issues.append(CorrectionReason("activity_mode", "Mode aktivitas wajib diisi."))
        return None
    aliases = {
        "transport": ActivityMode.TRANSPORT,
        "angkut": ActivityMode.TRANSPORT,
        "lifting": ActivityMode.LIFTING,
        "transport and lifting": ActivityMode.TRANSPORT_AND_LIFTING,
        "transport lifting": ActivityMode.TRANSPORT_AND_LIFTING,
        "angkut dan lifting": ActivityMode.TRANSPORT_AND_LIFTING,
    }
    mode = aliases.get(normalized_value(raw_value).replace("_", " "))
    if mode is None:
        issues.append(CorrectionReason("activity_mode", "Mode aktivitas tidak valid."))
    return mode


def parse_distance_source(
    raw_value: RawValue | None, issues: list[CorrectionReason]
) -> DistanceSource | None:
    if is_blank(raw_value):
        issues.append(CorrectionReason("distance_source", "Sumber jarak wajib diisi."))
        return None
    aliases = {
        "manual": DistanceSource.MANUAL,
        "routing provider": DistanceSource.ROUTING_PROVIDER,
        "penyedia rute": DistanceSource.ROUTING_PROVIDER,
    }
    source = aliases.get(normalized_value(raw_value).replace("_", " "))
    if source is None:
        issues.append(CorrectionReason("distance_source", "Sumber jarak tidak valid."))
    return source


def parse_number(
    raw_value: RawValue | None,
    field: str,
    issues: list[CorrectionReason],
    *,
    required: bool = False,
) -> float | None:
    if is_blank(raw_value):
        if required:
            issues.append(CorrectionReason(field, f"{_FIELD_LABELS[field]} wajib diisi."))
        return None
    if isinstance(raw_value, bool):
        issues.append(CorrectionReason(field, f"{_FIELD_LABELS[field]} harus berupa angka."))
        return None
    assert raw_value is not None
    if isinstance(raw_value, str):
        normalized = raw_value.strip()
        if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", normalized):
            issues.append(CorrectionReason(field, f"{_FIELD_LABELS[field]} harus berupa angka."))
            return None
        normalized = normalized.replace(",", ".")
        number = float(normalized)
    else:
        assert isinstance(raw_value, (int, float))
        number = float(raw_value)
    if not isfinite(number):
        issues.append(CorrectionReason(field, f"{_FIELD_LABELS[field]} harus berupa angka."))
        return None
    return number


def normalized_value(value: RawValue) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def _new_imported_operation_id() -> str:
    return f"IMPR-{uuid4().hex.upper()}"
