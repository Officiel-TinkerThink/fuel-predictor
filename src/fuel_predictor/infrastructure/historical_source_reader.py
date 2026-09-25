import csv
from collections.abc import Iterator
from datetime import date, datetime, time
from io import BytesIO, StringIO
from pathlib import Path

from openpyxl import load_workbook

from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetImportError,
    SourceSheet,
)
from fuel_predictor.domain.historical_dataset import RawValue

# Far above a day's plan or a year of history, far below what would strain
# the server: every upload is read whole into memory before it is checked.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_ROWS = 20_000


class SpreadsheetHistoricalDatasetSourceReader:
    def __init__(self, max_bytes: int = MAX_UPLOAD_BYTES, max_rows: int = MAX_UPLOAD_ROWS) -> None:
        self._max_bytes = max_bytes
        self._max_rows = max_rows

    def read(self, filename: str, content: bytes) -> tuple[SourceSheet, ...]:
        if len(content) > self._max_bytes:
            raise HistoricalDatasetImportError(
                f"Berkas terlalu besar: maksimal {self._max_bytes // (1024 * 1024)} MB. "
                "Bagi menjadi beberapa berkas."
            )
        suffix = Path(filename).suffix.casefold()
        if suffix == ".csv":
            return (self._read_csv(content),)
        if suffix == ".xlsx":
            return self._read_xlsx(content)
        raise HistoricalDatasetImportError(
            "Format berkas tidak didukung. Gunakan CSV atau Excel .xlsx."
        )

    def _read_csv(self, content: bytes) -> SourceSheet:
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HistoricalDatasetImportError("CSV harus menggunakan pengodean UTF-8.") from error
        try:
            dialect = csv.Sniffer().sniff(decoded, delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(StringIO(decoded), dialect=dialect))
        if not rows:
            raise HistoricalDatasetImportError("Berkas impor tidak memiliki baris header.")
        self._check_row_count(len(rows) - 1)
        headers = tuple(_header(value) for value in rows[0])
        return SourceSheet(
            name="CSV",
            headers=headers,
            rows=tuple(
                (index, tuple(row[: len(headers)]) + ("",) * (len(headers) - len(row)))
                for index, row in enumerate(rows[1:], start=2)
            ),
        )

    def _read_xlsx(self, content: bytes) -> tuple[SourceSheet, ...]:
        try:
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        except Exception as error:
            raise HistoricalDatasetImportError("Berkas Excel tidak dapat dibaca.") from error

        sheets: list[SourceSheet] = []
        total = 0
        for worksheet in workbook.worksheets:
            rows = self._rows_until_limit(worksheet.iter_rows(values_only=True), total)
            if not rows:
                continue
            total += len(rows) - 1
            headers = tuple(_header(value) for value in rows[0])
            sheets.append(
                SourceSheet(
                    name=worksheet.title,
                    headers=headers,
                    rows=tuple(
                        (
                            index,
                            tuple(_raw_value(value) for value in row)
                            + (None,) * (len(headers) - len(row)),
                        )
                        for index, row in enumerate(rows[1:], start=2)
                    ),
                )
            )
        if not sheets:
            raise HistoricalDatasetImportError("Berkas Excel tidak memiliki lembar data.")
        return tuple(sheets)

    def _rows_until_limit(
        self, rows: Iterator[tuple[object, ...]], already: int
    ) -> list[tuple[object, ...]]:
        """A sheet's rows, read one at a time so an oversized sheet stops early.
        Empty rows at the end are formatting, not data: a sheet styled down to
        its last row would otherwise be a million blank rows."""
        kept: list[tuple[object, ...]] = []
        blank_run: list[tuple[object, ...]] = []
        for row in rows:
            if all(value is None for value in row):
                blank_run.append(row)
                continue
            kept.extend(blank_run)
            blank_run.clear()
            kept.append(row)
            self._check_row_count(already + len(kept) - 1)
        return kept

    def _check_row_count(self, data_rows: int) -> None:
        if data_rows > self._max_rows:
            raise HistoricalDatasetImportError(
                f"Berkas berisi lebih dari {self._max_rows:,} baris; ".replace(",", ".")
                + "bagi menjadi beberapa berkas."
            )


def _header(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _raw_value(value: object) -> RawValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)
