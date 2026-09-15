"""Past operations for the similar-history search, out of the tables that
already hold them. No schema of its own: it reads what the importer, the
prediction path and the actual-fuel path each wrote (ADR 0002 keeps prepared
and actual fuel in separate places, and this keeps them separate on the way
out too)."""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fuel_predictor.application.historical_datasets import normalize_header
from fuel_predictor.application.similar_operations import (
    HistoricalOperationRecord,
    HistorySource,
)
from fuel_predictor.domain.daily_operation import ActivityMode, DistanceSource, VehicleCategory
from fuel_predictor.domain.prediction import ModelLifecycleStatus
from fuel_predictor.infrastructure.database import (
    ActualFuelRecordRow,
    DailyOperationRow,
    DailyOperationStopRow,
    DatasetVersionRow,
    HistoricalDailyOperationRow,
    ModelVersionRow,
    PredictionRow,
    SessionFactory,
)

# An installation that has run for years has more recorded operations than a
# planner will ever page through; the newest few thousand are what "recent
# history" means, and holding them in memory to rank is cheap.
_MAX_RECORDED_ROWS = 5000

_DATE_HEADERS = {"tanggal", "tgl", "date", "hari tanggal", "tanggal operasi"}


class SqlAlchemyHistoricalOperationSource:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def dataset_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        """Rows of the dataset the active model was trained on — the history the
        recommendation actually comes from — or, before any model is active,
        the newest import."""
        with self._session_factory() as session:
            dataset = self._preferred_dataset(session)
            if dataset is None:
                return ()
            rows = session.scalars(
                select(HistoricalDailyOperationRow)
                .where(
                    HistoricalDailyOperationRow.dataset_version_id == dataset.dataset_version_id,
                    HistoricalDailyOperationRow.vehicle_category == vehicle_category.value,
                )
                .order_by(HistoricalDailyOperationRow.source_order)
            ).all()
            return tuple(_dataset_record(row, dataset.source_filename) for row in rows)

    def recorded_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        """Operations planned through the app or an agent, with the estimate
        they were given and the actual fuel if one was entered since. A bare
        operation with neither is a plan that never went anywhere; it tells a
        planner nothing about fuel and is left out."""
        latest_prediction_id = (
            select(PredictionRow.prediction_id)
            .where(PredictionRow.operation_id == DailyOperationRow.operation_id)
            .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
            .limit(1)
            .correlate(DailyOperationRow)
            .scalar_subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(DailyOperationRow, PredictionRow, ActualFuelRecordRow)
                .select_from(DailyOperationRow)
                .outerjoin(PredictionRow, PredictionRow.prediction_id == latest_prediction_id)
                .outerjoin(
                    ActualFuelRecordRow,
                    ActualFuelRecordRow.operation_id == DailyOperationRow.operation_id,
                )
                .where(
                    DailyOperationRow.vehicle_category == vehicle_category.value,
                    (PredictionRow.prediction_id.is_not(None))
                    | (ActualFuelRecordRow.operation_id.is_not(None)),
                )
                .order_by(
                    PredictionRow.created_at.desc().nulls_last(),
                    DailyOperationRow.operation_id.desc(),
                )
                .limit(_MAX_RECORDED_ROWS)
            ).all()
            stops = _stops_for(session, [row.DailyOperationRow.operation_id for row in rows])
            return tuple(
                _recorded_record(
                    row.DailyOperationRow,
                    row.PredictionRow,
                    row.ActualFuelRecordRow,
                    stops.get(row.DailyOperationRow.operation_id, ()),
                )
                for row in rows
            )

    @staticmethod
    def _preferred_dataset(session: Session) -> DatasetVersionRow | None:
        active = session.scalar(
            select(ModelVersionRow).where(
                ModelVersionRow.lifecycle_status == ModelLifecycleStatus.ACTIVE.value
            )
        )
        if active is not None:
            trained_on = session.scalar(
                select(DatasetVersionRow).where(
                    DatasetVersionRow.dataset_version_id == active.dataset_version_id
                )
            )
            # An ingested package names a dataset from the builder's machine
            # (ADR 0009); when that is not one of ours, the newest import is
            # still the best history this installation has.
            if trained_on is not None:
                return trained_on
        return session.scalar(
            select(DatasetVersionRow).order_by(DatasetVersionRow.version.desc()).limit(1)
        )


def _stops_for(session: Session, operation_ids: list[str]) -> dict[str, tuple[str, ...]]:
    if not operation_ids:
        return {}
    ordered: defaultdict[str, list[str]] = defaultdict(list)
    for operation_id, location_name in session.execute(
        select(DailyOperationStopRow.operation_id, DailyOperationStopRow.location_name)
        .where(DailyOperationStopRow.operation_id.in_(operation_ids))
        .order_by(DailyOperationStopRow.operation_id, DailyOperationStopRow.stop_position)
    ):
        ordered[operation_id].append(location_name)
    return {operation_id: tuple(stops) for operation_id, stops in ordered.items()}


def _dataset_record(
    row: HistoricalDailyOperationRow, source_filename: str
) -> HistoricalOperationRecord:
    return HistoricalOperationRecord(
        source=HistorySource.DATASET,
        operation_id=row.operation_id,
        vehicle=row.vehicle,
        vehicle_category=VehicleCategory(row.vehicle_category),
        activity_mode=ActivityMode(row.activity_mode),
        lifting_hours=row.lifting_hours,
        total_distance_km=row.total_distance_km,
        distance_source=DistanceSource(row.distance_source),
        prepared_fuel_liters=row.prepared_fuel_liters,
        operation_date=_date_written_in(row.raw_values),
        source_reference=f"{source_filename} / {row.sheet_name} / baris {row.row_number}",
    )


def _recorded_record(
    operation: DailyOperationRow,
    prediction: PredictionRow | None,
    actual: ActualFuelRecordRow | None,
    stops: tuple[str, ...],
) -> HistoricalOperationRecord:
    return HistoricalOperationRecord(
        source=HistorySource.RECORDED,
        operation_id=operation.operation_id,
        vehicle=operation.vehicle,
        vehicle_category=VehicleCategory(operation.vehicle_category),
        activity_mode=ActivityMode(operation.activity_mode),
        lifting_hours=operation.lifting_hours,
        total_distance_km=operation.total_distance_km,
        distance_source=DistanceSource(operation.distance_source),
        stop_sequence=stops or None,
        estimated_fuel_requirement_liters=(
            prediction.estimated_fuel_requirement_liters if prediction else None
        ),
        recommended_allocation_liters=(
            prediction.recommended_allocation_liters if prediction else None
        ),
        actual_fuel_liters=actual.actual_fuel_liters if actual else None,
        recorded_at=_recorded_at(prediction, actual),
    )


def _recorded_at(
    prediction: PredictionRow | None, actual: ActualFuelRecordRow | None
) -> datetime | None:
    """When it was planned; failing that, when its fuel was entered."""
    if prediction is not None:
        return prediction.created_at
    return actual.recorded_at if actual is not None else None


def _date_written_in(raw_values: dict[str, object]) -> str | None:
    """The sheet's own date column, if the import kept one. Header spellings
    vary as much as everything else in those sheets, hence the alias set."""
    for header, value in raw_values.items():
        if normalize_header(header) in _DATE_HEADERS and value not in (None, ""):
            return str(value)
    return None
