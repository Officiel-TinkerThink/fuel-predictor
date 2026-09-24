from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fuel_predictor.application.daily_operations import OperationCodeTakenError
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
        try:
            self._insert(operation)
        except IntegrityError:
            # Only a code that is now held is a lost race worth retrying; any
            # other violation is a real error.
            if operation.operation_code is not None and self._code_is_held(
                operation.operation_code
            ):
                raise OperationCodeTakenError(operation.operation_code) from None
            raise

    def codes_taken(self, base: str) -> set[str]:
        with self._session_factory() as session:
            codes = session.scalars(
                select(DailyOperationRow.operation_code).where(
                    or_(
                        DailyOperationRow.operation_code == base,
                        DailyOperationRow.operation_code.startswith(f"{base}-", autoescape=True),
                    )
                )
            )
            return {code for code in codes if code is not None}

    def get_by_code(self, operation_code: str) -> DailyOperation | None:
        with self._session_factory() as session:
            operation_id = session.scalar(
                select(DailyOperationRow.operation_id).where(
                    DailyOperationRow.operation_code == operation_code
                )
            )
        return None if operation_id is None else self.get(operation_id)

    def _code_is_held(self, operation_code: str) -> bool:
        return self.get_by_code(operation_code) is not None

    def _insert(self, operation: DailyOperation) -> None:
        with self._session_factory.begin() as session:
            session.add(
                DailyOperationRow(
                    operation_id=operation.operation_id,
                    operation_code=operation.operation_code,
                    vehicle_category=operation.vehicle_category.value,
                    vehicle=operation.vehicle,
                    activity_mode=operation.activity_mode.value,
                    lifting_hours=operation.lifting_hours,
                    total_distance_km=operation.total_distance_km,
                    distance_source=operation.distance_source.value,
                    created_by=operation.created_by,
                    created_at=operation.created_at,
                    route_distance_manual_fallback=operation.route_distance_manual_fallback,
                )
            )
            activities = operation.stop_activities or ()
            session.add_all(
                DailyOperationStopRow(
                    operation_id=operation.operation_id,
                    stop_position=position,
                    location_name=location_name,
                    activity=(activities[position] or None) if position < len(activities) else None,
                )
                for position, location_name in enumerate(operation.stop_sequence)
            )

    def get(self, operation_id: str) -> DailyOperation | None:
        with self._session_factory() as session:
            row = session.get(DailyOperationRow, operation_id)
            if row is None:
                return None
            stop_rows = tuple(
                session.execute(
                    select(
                        DailyOperationStopRow.location_name,
                        DailyOperationStopRow.activity,
                    )
                    .where(DailyOperationStopRow.operation_id == operation_id)
                    .order_by(DailyOperationStopRow.stop_position)
                )
            )
            stops = tuple(stop.location_name for stop in stop_rows)
            activities = tuple(stop.activity or "" for stop in stop_rows)
            return _to_domain(row, stops, activities if any(activities) else ())

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


def stops_for(session: Session, operation_ids: Sequence[str]) -> dict[str, list[str]]:
    """Stop names per operation, in planner order, for a batch of operations.

    Readers that rebuild a DailyOperation from a row need these: the domain
    invariant for a manual-fallback route requires a stop sequence.
    """
    stops: dict[str, list[str]] = defaultdict(list)
    if not operation_ids:
        return stops
    for stop in session.execute(
        select(DailyOperationStopRow.operation_id, DailyOperationStopRow.location_name)
        .where(DailyOperationStopRow.operation_id.in_(list(operation_ids)))
        .order_by(DailyOperationStopRow.operation_id, DailyOperationStopRow.stop_position)
    ):
        stops[stop.operation_id].append(stop.location_name)
    return stops


def _to_domain(
    row: DailyOperationRow,
    stop_sequence: tuple[str, ...],
    stop_activities: tuple[str, ...] = (),
) -> DailyOperation:
    return DailyOperation(
        operation_id=row.operation_id,
        vehicle_category=VehicleCategory(row.vehicle_category),
        vehicle=row.vehicle,
        activity_mode=ActivityMode(row.activity_mode),
        lifting_hours=row.lifting_hours,
        total_distance_km=row.total_distance_km,
        distance_source=DistanceSource(row.distance_source),
        stop_sequence=stop_sequence,
        stop_activities=stop_activities,
        route_distance_manual_fallback=row.route_distance_manual_fallback,
        created_by=row.created_by,
        created_at=row.created_at,
        operation_code=row.operation_code,
    )
