import sqlite3
from pathlib import Path

from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)


class SqliteDailyOperationRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def add(self, operation: DailyOperation) -> None:
        self._initialize_schema()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_operations (
                    operation_id,
                    vehicle_category,
                    activity_mode,
                    lifting_hours,
                    total_distance_km,
                    distance_source,
                    route_distance_manual_fallback
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.operation_id,
                    operation.vehicle_category.value,
                    operation.activity_mode.value,
                    operation.lifting_hours,
                    operation.total_distance_km,
                    operation.distance_source.value,
                    operation.route_distance_manual_fallback,
                ),
            )
            connection.executemany(
                """
                INSERT INTO daily_operation_stops (operation_id, stop_position, location_name)
                VALUES (?, ?, ?)
                """,
                [
                    (operation.operation_id, position, location_name)
                    for position, location_name in enumerate(operation.stop_sequence)
                ],
            )

    def get(self, operation_id: str) -> DailyOperation | None:
        self._initialize_schema()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT operation_id, vehicle_category, activity_mode, lifting_hours,
                       total_distance_km, distance_source, route_distance_manual_fallback
                FROM daily_operations
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        with self._connect() as connection:
            stops = tuple(
                str(stop[0])
                for stop in connection.execute(
                    """
                    SELECT location_name FROM daily_operation_stops
                    WHERE operation_id = ? ORDER BY stop_position
                    """,
                    (operation_id,),
                )
            )
        return DailyOperation(
            operation_id=str(row[0]),
            vehicle_category=VehicleCategory(str(row[1])),
            activity_mode=ActivityMode(str(row[2])),
            lifting_hours=float(row[3]) if row[3] is not None else None,
            total_distance_km=float(row[4]),
            distance_source=DistanceSource(str(row[5])),
            stop_sequence=stops,
            route_distance_manual_fallback=bool(row[6]),
        )

    def _initialize_schema(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_operations (
                    operation_id TEXT PRIMARY KEY,
                    vehicle_category TEXT NOT NULL,
                    activity_mode TEXT NOT NULL,
                    lifting_hours REAL,
                    total_distance_km REAL NOT NULL,
                    distance_source TEXT NOT NULL,
                    route_distance_manual_fallback INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_operation_stops (
                    operation_id TEXT NOT NULL,
                    stop_position INTEGER NOT NULL,
                    location_name TEXT NOT NULL,
                    PRIMARY KEY (operation_id, stop_position),
                    FOREIGN KEY (operation_id) REFERENCES daily_operations(operation_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)
