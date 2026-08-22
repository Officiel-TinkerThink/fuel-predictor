from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ActualFuelMeasurementSource(StrEnum):
    MANUAL_ENTRY = "manual_entry"
    FUEL_METER = "fuel_meter"
    RECEIPT = "receipt"
    SPREADSHEET_IMPORT = "spreadsheet_import"


class ActualFuelStatus(StrEnum):
    RECORDED = "recorded"


@dataclass(frozen=True, slots=True)
class ActualFuelRecord:
    operation_id: str
    actual_fuel_liters: float
    measurement_source: ActualFuelMeasurementSource
    status: ActualFuelStatus
    recorded_at: datetime
    source_filename: str | None = None
    source_sheet_name: str | None = None
    source_row_number: int | None = None
