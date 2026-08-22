from dataclasses import dataclass
from datetime import datetime

from fuel_predictor.domain.daily_operation import DailyOperation

type RawValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    sheet_name: str
    row_number: int
    original_headers: dict[str, str]
    raw_values: dict[str, RawValue]
    source_filename: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalDailyOperation:
    operation: DailyOperation
    prepared_fuel_liters: float
    source: SourceProvenance


@dataclass(frozen=True, slots=True)
class CorrectionReason:
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    source: SourceProvenance
    reasons: tuple[CorrectionReason, ...]


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_version_id: str
    version: int
    source_filename: str
    imported_at: datetime
    valid_operation_count: int
    quarantined_row_count: int
    ignored_blank_row_count: int
