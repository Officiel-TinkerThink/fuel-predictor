"""Every planned operation gets an operation code when it is created.

The code is formed in the site's time zone from the creation time and the
vehicle, and it is unique: the same vehicle twice in one minute - almost always
a double submission - gets a `-2` suffix instead of a clash.
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from alembic import command
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    CreateDailyOperationCommand,
    OperationCodeTakenError,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import (
    SqlAlchemyDailyOperationRepository,
)
from fuel_predictor.main import create_app

_JAKARTA = ZoneInfo("Asia/Jakarta")
# 09:14 in Jakarta.
_MORNING = datetime(2026, 9, 23, 2, 14, 5, tzinfo=UTC)


def _repository(tmp_path: Path) -> SqlAlchemyDailyOperationRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'codes.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyDailyOperationRepository(build_session_factory(engine))


def _command(vehicle: str | None = "VT 01") -> CreateDailyOperationCommand:
    return CreateDailyOperationCommand(
        vehicle_category=VehicleCategory.ANGBER,
        vehicle=vehicle,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=20,
        distance_source=DistanceSource.MANUAL,
    )


def _create(
    repository: SqlAlchemyDailyOperationRepository, moment: datetime = _MORNING
) -> CreateDailyOperation:
    return CreateDailyOperation(repository, now=lambda: moment, site_timezone=_JAKARTA)


def test_the_code_is_the_site_local_minute_and_the_vehicle(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    operation = _create(repository).execute(_command())

    assert operation.operation_code == "260923-0914-VT01"
    stored = repository.get(operation.operation_id)
    assert stored is not None
    assert stored.operation_code == "260923-0914-VT01"


def test_the_date_is_the_site_date_not_the_utc_one(tmp_path: Path) -> None:
    # 23:30 UTC on the 22nd is already 06:30 on the 23rd in Jakarta.
    late = datetime(2026, 9, 22, 23, 30, tzinfo=UTC)

    operation = _create(_repository(tmp_path), late).execute(_command())

    assert operation.operation_code == "260923-0630-VT01"


def test_the_same_vehicle_again_in_the_same_minute_gets_a_suffix(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    create = _create(repository)

    codes = [create.execute(_command()).operation_code for _ in range(3)]
    other_vehicle = create.execute(_command("Truck Crane 01")).operation_code

    assert codes == ["260923-0914-VT01", "260923-0914-VT01-2", "260923-0914-VT01-3"]
    assert other_vehicle == "260923-0914-TC01"


def test_an_operation_without_a_vehicle_is_coded_by_time_alone(tmp_path: Path) -> None:
    operation = _create(_repository(tmp_path)).execute(_command(vehicle=None))

    assert operation.operation_code == "260923-0914"


def test_the_code_is_found_by_the_code(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    operation = _create(repository).execute(_command())

    found = repository.get_by_code("260923-0914-VT01")

    assert found is not None
    assert found.operation_id == operation.operation_id
    assert repository.get_by_code("260923-0914-VT02") is None


class _RacingRepository:
    """Another request stores the chosen code between the lookup and the insert."""

    def __init__(self, inner: SqlAlchemyDailyOperationRepository) -> None:
        self._inner = inner
        self.lost_races = 0

    def codes_taken(self, base: str) -> set[str]:
        return self._inner.codes_taken(base)

    def add(self, operation: DailyOperation) -> None:
        if self.lost_races == 0:
            self.lost_races += 1
            _create(self._inner).execute(_command())
        self._inner.add(operation)


def test_a_code_taken_by_a_concurrent_request_is_retried_with_the_next_suffix(
    tmp_path: Path,
) -> None:
    inner = _repository(tmp_path)
    racing = _RacingRepository(inner)

    operation = CreateDailyOperation(racing, now=lambda: _MORNING, site_timezone=_JAKARTA).execute(
        _command()
    )

    assert racing.lost_races == 1
    assert operation.operation_code == "260923-0914-VT01-2"
    assert inner.get_by_code("260923-0914-VT01") is not None


def test_storing_a_taken_code_says_so(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _create(repository).execute(_command())
    duplicate = DailyOperation(
        operation_id="OPR-DUPLICATE",
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=ActivityMode.TRANSPORT,
        lifting_hours=None,
        total_distance_km=20,
        distance_source=DistanceSource.MANUAL,
        operation_code=first.operation_code,
    )

    try:
        repository.add(duplicate)
    except OperationCodeTakenError:
        pass
    else:
        raise AssertionError("a second operation took an existing code")
    assert repository.get("OPR-DUPLICATE") is None


def test_the_api_returns_the_code_of_a_new_operation(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        created = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 12,
                "distance_source": "manual",
            },
        ).json()
        fetched = client.get(f"/api/v1/daily-operations/{created['operation_id']}").json()

    assert created["operation_code"]
    assert fetched["operation_code"] == created["operation_code"]


def test_the_migration_codes_existing_planned_operations_and_leaves_imports_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A populated deployment upgrades with a code on every operation someone planned,
    so the ones already waiting for actual fuel can be recorded by code too."""
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}"
    monkeypatch.setenv("FUEL_PREDICTOR_DATABASE_URL", database_url)
    monkeypatch.delenv("FUEL_PREDICTOR_SITE_TIMEZONE", raising=False)
    config = Config("alembic.ini")
    command.upgrade(config, "20260922_27")
    engine = create_engine(database_url)
    insert = text(
        "INSERT INTO daily_operations (operation_id, vehicle_category, vehicle, activity_mode,"
        " total_distance_km, distance_source, route_distance_manual_fallback, created_at)"
        " VALUES (:id, 'ANGBER', :vehicle, 'transport', 10, 'manual', 0, :created_at)"
    )
    with engine.begin() as connection:
        for operation_id, vehicle, created_at in (
            ("OPR-B", "VT 01", "2026-09-23 02:14:40"),
            ("OPR-A", "VT 01", "2026-09-23 02:14:05"),
            ("OPR-C", "Truck Crane 01", "2026-09-22 23:30:00"),
            ("OPR-D", None, "2026-09-23 02:14:00"),
            ("IMPR-E", "VT 01", None),
        ):
            connection.execute(
                insert, {"id": operation_id, "vehicle": vehicle, "created_at": created_at}
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        codes = dict(
            connection.execute(text("SELECT operation_id, operation_code FROM daily_operations"))
            .tuples()
            .all()
        )
    assert codes == {
        # Creation order decides who keeps the bare code.
        "OPR-A": "260923-0914-VT01",
        "OPR-B": "260923-0914-VT01-2",
        "OPR-C": "260923-0630-TC01",
        "OPR-D": "260923-0914",
        "IMPR-E": None,
    }

    command.downgrade(config, "20260922_27")
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("daily_operations")}
    assert "operation_code" not in columns
