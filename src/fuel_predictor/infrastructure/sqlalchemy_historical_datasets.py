from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import select

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
from fuel_predictor.infrastructure.database import (
    DataQualityIssueRow,
    DatasetVersionRow,
    HistoricalDailyOperationRow,
    SessionFactory,
)


class SqlAlchemyHistoricalDatasetRepository(HistoricalDatasetWriter, HistoricalDatasetReader):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create(
        self,
        source_filename: str,
        valid_operations: Sequence[HistoricalDailyOperation],
        issues: Sequence[DataQualityIssue],
        ignored_blank_row_count: int,
    ) -> DatasetVersion:
        imported_at = datetime.now(UTC)
        with self._session_factory.begin() as session:
            dataset = DatasetVersionRow(
                dataset_version_id=f"pending-{uuid4().hex[:24]}",
                source_filename=source_filename,
                imported_at=imported_at,
                valid_operation_count=len(valid_operations),
                quarantined_row_count=len(issues),
                ignored_blank_row_count=ignored_blank_row_count,
            )
            session.add(dataset)
            # First flush assigns the autoincrement `version`, which the real
            # identifier is derived from.
            session.flush()
            dataset.dataset_version_id = f"DSV-{dataset.version:06d}"
            # Second flush lands that rename before any child rows reference it.
            # Without it the parent still holds its placeholder id while the
            # children are inserted against the final one, and whether that
            # works depends on the order SQLAlchemy happens to emit statements
            # in. PostgreSQL rejects it outright; SQLite accepted it silently
            # only because foreign keys were not being enforced.
            session.flush()
            for source_order, operation in enumerate(valid_operations):
                session.add(
                    _valid_operation_row(dataset.dataset_version_id, operation, source_order)
                )
            for issue in issues:
                session.add(_issue_row(dataset.dataset_version_id, issue))
            result = _to_dataset_version(dataset)
        return result

    def get_valid_operations(
        self, dataset_version_id: str
    ) -> tuple[HistoricalDailyOperation, ...] | None:
        with self._session_factory() as session:
            dataset = session.scalar(
                select(DatasetVersionRow).where(
                    DatasetVersionRow.dataset_version_id == dataset_version_id
                )
            )
            if dataset is None:
                return None
            rows = session.scalars(
                select(HistoricalDailyOperationRow)
                .where(HistoricalDailyOperationRow.dataset_version_id == dataset_version_id)
                .order_by(HistoricalDailyOperationRow.source_order)
            )
            return tuple(_to_historical_operation(row) for row in rows)


def _valid_operation_row(
    dataset_version_id: str,
    historical_operation: HistoricalDailyOperation,
    source_order: int,
) -> HistoricalDailyOperationRow:
    operation = historical_operation.operation
    source = historical_operation.source
    return HistoricalDailyOperationRow(
        dataset_version_id=dataset_version_id,
        operation_id=operation.operation_id,
        vehicle_category=operation.vehicle_category.value,
        vehicle=operation.vehicle,
        activity_mode=operation.activity_mode.value,
        lifting_hours=operation.lifting_hours,
        total_distance_km=operation.total_distance_km,
        distance_source=operation.distance_source.value,
        prepared_fuel_liters=historical_operation.prepared_fuel_liters,
        sheet_name=source.sheet_name,
        row_number=source.row_number,
        original_headers=source.original_headers,
        raw_values=cast(dict[str, object], source.raw_values),
        source_order=source_order,
    )


def _issue_row(dataset_version_id: str, issue: DataQualityIssue) -> DataQualityIssueRow:
    return DataQualityIssueRow(
        dataset_version_id=dataset_version_id,
        sheet_name=issue.source.sheet_name,
        row_number=issue.source.row_number,
        original_headers=issue.source.original_headers,
        reasons=[{"field": reason.field, "message": reason.message} for reason in issue.reasons],
        raw_values=cast(dict[str, object], issue.source.raw_values),
    )


def _to_dataset_version(row: DatasetVersionRow) -> DatasetVersion:
    return DatasetVersion(
        dataset_version_id=row.dataset_version_id,
        version=row.version,
        source_filename=row.source_filename,
        imported_at=row.imported_at,
        valid_operation_count=row.valid_operation_count,
        quarantined_row_count=row.quarantined_row_count,
        ignored_blank_row_count=row.ignored_blank_row_count,
    )


def _to_historical_operation(row: HistoricalDailyOperationRow) -> HistoricalDailyOperation:
    return HistoricalDailyOperation(
        operation=DailyOperation(
            operation_id=row.operation_id,
            vehicle_category=VehicleCategory(row.vehicle_category),
            vehicle=row.vehicle,
            activity_mode=ActivityMode(row.activity_mode),
            lifting_hours=row.lifting_hours,
            total_distance_km=row.total_distance_km,
            distance_source=DistanceSource(row.distance_source),
        ),
        prepared_fuel_liters=row.prepared_fuel_liters,
        source=SourceProvenance(
            sheet_name=row.sheet_name,
            row_number=row.row_number,
            original_headers=row.original_headers,
            raw_values=cast(dict[str, RawValue], row.raw_values),
        ),
    )
