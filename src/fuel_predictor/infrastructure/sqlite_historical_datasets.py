import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fuel_predictor.application.historical_datasets import (
    HistoricalDatasetReader,
    HistoricalDatasetWriter,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.historical_dataset import (
    DataQualityIssue,
    DatasetVersion,
    HistoricalDailyOperation,
    RawValue,
    SourceProvenance,
)


class SqliteHistoricalDatasetRepository(HistoricalDatasetWriter, HistoricalDatasetReader):
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def create(
        self,
        source_filename: str,
        valid_operations: Sequence[HistoricalDailyOperation],
        issues: Sequence[DataQualityIssue],
        ignored_blank_row_count: int,
    ) -> DatasetVersion:
        self._initialize_schema()
        imported_at = datetime.now(UTC)
        with self._connect() as connection:
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM dataset_versions"
            ).fetchone()
            assert version_row is not None
            next_version = int(cast(int, version_row[0]))
            dataset_version_id = f"DSV-{next_version:06d}"
            connection.execute(
                """
                INSERT INTO dataset_versions (
                    dataset_version_id, version, source_filename, imported_at,
                    valid_operation_count, quarantined_row_count, ignored_blank_row_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_version_id,
                    next_version,
                    source_filename,
                    imported_at.isoformat(),
                    len(valid_operations),
                    len(issues),
                    ignored_blank_row_count,
                ),
            )
            for operation in valid_operations:
                self._insert_valid_operation(connection, dataset_version_id, operation)
            for issue in issues:
                connection.execute(
                    """
                    INSERT INTO data_quality_issues (
                        dataset_version_id, sheet_name, row_number, reasons_json, raw_values_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_version_id,
                        issue.source.sheet_name,
                        issue.source.row_number,
                        json.dumps(
                            [
                                {"field": reason.field, "message": reason.message}
                                for reason in issue.reasons
                            ]
                        ),
                        json.dumps(issue.source.raw_values),
                    ),
                )
        return DatasetVersion(
            dataset_version_id=dataset_version_id,
            version=next_version,
            source_filename=source_filename,
            imported_at=imported_at,
            valid_operation_count=len(valid_operations),
            quarantined_row_count=len(issues),
            ignored_blank_row_count=ignored_blank_row_count,
        )

    def get_valid_operations(
        self, dataset_version_id: str
    ) -> tuple[HistoricalDailyOperation, ...] | None:
        self._initialize_schema()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM dataset_versions WHERE dataset_version_id = ?", (dataset_version_id,)
            ).fetchone()
            if exists is None:
                return None
            rows = connection.execute(
                """
                SELECT operation_id, vehicle_category, activity_mode, lifting_hours,
                       total_distance_km, distance_source, prepared_fuel_liters,
                       sheet_name, row_number, original_headers_json, raw_values_json
                FROM historical_daily_operations
                WHERE dataset_version_id = ?
                ORDER BY source_order
                """,
                (dataset_version_id,),
            ).fetchall()
        return tuple(self._to_historical_operation(row) for row in rows)

    def _insert_valid_operation(
        self,
        connection: sqlite3.Connection,
        dataset_version_id: str,
        historical_operation: HistoricalDailyOperation,
    ) -> None:
        operation = historical_operation.operation
        source = historical_operation.source
        connection.execute(
            """
            INSERT INTO historical_daily_operations (
                dataset_version_id, operation_id, vehicle_category, activity_mode, lifting_hours,
                total_distance_km, distance_source, prepared_fuel_liters, sheet_name, row_number,
                original_headers_json, raw_values_json, source_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_version_id,
                operation.operation_id,
                operation.vehicle_category.value,
                operation.activity_mode.value,
                operation.lifting_hours,
                operation.total_distance_km,
                operation.distance_source.value,
                historical_operation.prepared_fuel_liters,
                source.sheet_name,
                source.row_number,
                json.dumps(source.original_headers),
                json.dumps(source.raw_values),
                source.row_number,
            ),
        )

    def _to_historical_operation(
        self, row: sqlite3.Row | tuple[object, ...]
    ) -> HistoricalDailyOperation:
        return HistoricalDailyOperation(
            operation=DailyOperation(
                operation_id=str(row[0]),
                vehicle_category=VehicleCategory(str(row[1])),
                activity_mode=ActivityMode(str(row[2])),
                lifting_hours=float(cast(int | float | str, row[3]))
                if row[3] is not None
                else None,
                total_distance_km=float(cast(int | float | str, row[4])),
                distance_source=DistanceSource(str(row[5])),
            ),
            prepared_fuel_liters=float(cast(int | float | str, row[6])),
            source=SourceProvenance(
                sheet_name=str(row[7]),
                row_number=int(cast(int | str, row[8])),
                original_headers=cast(dict[str, str], json.loads(str(row[9]))),
                raw_values=cast(dict[str, RawValue], json.loads(str(row[10]))),
            ),
        )

    def _initialize_schema(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    dataset_version_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL UNIQUE,
                    source_filename TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    valid_operation_count INTEGER NOT NULL,
                    quarantined_row_count INTEGER NOT NULL,
                    ignored_blank_row_count INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_daily_operations (
                    id INTEGER PRIMARY KEY,
                    dataset_version_id TEXT NOT NULL
                        REFERENCES dataset_versions(dataset_version_id),
                    operation_id TEXT NOT NULL,
                    vehicle_category TEXT NOT NULL,
                    activity_mode TEXT NOT NULL,
                    lifting_hours REAL,
                    total_distance_km REAL NOT NULL,
                    distance_source TEXT NOT NULL,
                    prepared_fuel_liters REAL NOT NULL,
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    original_headers_json TEXT NOT NULL,
                    raw_values_json TEXT NOT NULL,
                    source_order INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_quality_issues (
                    id INTEGER PRIMARY KEY,
                    dataset_version_id TEXT NOT NULL
                        REFERENCES dataset_versions(dataset_version_id),
                    sheet_name TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    reasons_json TEXT NOT NULL,
                    raw_values_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)
