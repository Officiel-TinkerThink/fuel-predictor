from sqlalchemy import select

from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.domain.historical_dataset import SourceProvenance
from fuel_predictor.infrastructure.database import (
    DailyOperationRow,
    DailyOperationSourceRow,
    DailyOperationStopRow,
    SessionFactory,
)


class SqlAlchemyDailyOperationRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def add(self, operation: DailyOperation) -> None:
        with self._session_factory.begin() as session:
            session.add(
                DailyOperationRow(
                    operation_id=operation.operation_id,
                    vehicle_category=operation.vehicle_category.value,
                    activity_mode=operation.activity_mode.value,
                    lifting_hours=operation.lifting_hours,
                    total_distance_km=operation.total_distance_km,
                    distance_source=operation.distance_source.value,
                    route_distance_manual_fallback=operation.route_distance_manual_fallback,
                )
            )
            session.add_all(
                DailyOperationStopRow(
                    operation_id=operation.operation_id,
                    stop_position=position,
                    location_name=location_name,
                )
                for position, location_name in enumerate(operation.stop_sequence)
            )

    def get(self, operation_id: str) -> DailyOperation | None:
        with self._session_factory() as session:
            row = session.get(DailyOperationRow, operation_id)
            if row is None:
                return None
            stops = tuple(
                session.scalars(
                    select(DailyOperationStopRow.location_name)
                    .where(DailyOperationStopRow.operation_id == operation_id)
                    .order_by(DailyOperationStopRow.stop_position)
                )
            )
            return _to_domain(row, stops)

    def add_source(self, operation_id: str, source: SourceProvenance) -> None:
        if source.source_filename is None:
            raise ValueError("Nama berkas sumber wajib dicatat untuk impor operasi massal.")
        with self._session_factory.begin() as session:
            session.add(
                DailyOperationSourceRow(
                    operation_id=operation_id,
                    source_filename=source.source_filename,
                    sheet_name=source.sheet_name,
                    row_number=source.row_number,
                    original_headers=source.original_headers,
                    raw_values=source.raw_values,
                )
            )


def _to_domain(row: DailyOperationRow, stop_sequence: tuple[str, ...]) -> DailyOperation:
    return DailyOperation(
        operation_id=row.operation_id,
        vehicle_category=VehicleCategory(row.vehicle_category),
        activity_mode=ActivityMode(row.activity_mode),
        lifting_hours=row.lifting_hours,
        total_distance_km=row.total_distance_km,
        distance_source=DistanceSource(row.distance_source),
        stop_sequence=stop_sequence,
        route_distance_manual_fallback=row.route_distance_manual_fallback,
    )
