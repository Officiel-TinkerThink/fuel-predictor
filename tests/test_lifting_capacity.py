"""Only a vehicle that can lift may be planned with lifting.

The catalog says which units have lifting capacity: the three cranes, the
only units the Data Ratio sheet gives a lift ratio. A vacuum truck planned
with "lifting" was accepted and its hours fed to the model. The planner now
chooses between two activities - Mobilisasi and Mobilisasi + lifting - and the
second is offered only for a unit that can lift. The form disables it for
the others, and every route in (form, API, bulk sheet, MCP) refuses it.
"""

import csv
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    CreateDailyOperationCommand,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperationValidationError,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.infrastructure.sqlalchemy_daily_operations import (
    SqlAlchemyDailyOperationRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository
from fuel_predictor.main import create_app

_LIFTING_UNITS = {"Truck Crane 01", "Truck Crane 02", "Wheel Crane"}
_DATA_RATIO = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "fuel_predictor"
    / "examples"
    / "data-ratio-angber.csv"
)


def test_the_cranes_and_only_the_cranes_can_lift() -> None:
    options = PackagedVehicleCatalog().options()

    assert {option.name for option in options if option.can_lift} == _LIFTING_UNITS


def test_every_unit_the_data_ratio_sheet_prices_lifting_for_can_lift() -> None:
    catalog = PackagedVehicleCatalog()
    with _DATA_RATIO.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.reader(handle) if row and re.fullmatch(r"\d+(\.0)?", row[0])]
    priced = set()
    for row in rows:
        option = catalog.find(row[1].split(" - ")[0].strip())
        assert option is not None
        if row[8].strip():
            priced.add(option.name)

    assert priced == _LIFTING_UNITS


def test_the_capacity_round_trips_through_the_vehicles_table(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'fleet.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    repository = SqlAlchemyVehicleRepository(build_session_factory(engine))

    repository.replace_all(PackagedVehicleCatalog().options())

    assert {option.name for option in repository.options() if option.can_lift} == _LIFTING_UNITS


def _create(tmp_path: Path) -> CreateDailyOperation:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'ops.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return CreateDailyOperation(
        SqlAlchemyDailyOperationRepository(build_session_factory(engine)),
        vehicle_catalog=PackagedVehicleCatalog(),
    )


def _command(vehicle: str, mode: ActivityMode) -> CreateDailyOperationCommand:
    return CreateDailyOperationCommand(
        vehicle_category=VehicleCategory.ANGBER,
        vehicle=vehicle,
        activity_mode=mode,
        lifting_hours=2.0 if mode is not ActivityMode.TRANSPORT else None,
        total_distance_km=20,
        distance_source=DistanceSource.MANUAL,
    )


@pytest.mark.parametrize("mode", [ActivityMode.TRANSPORT_AND_LIFTING, ActivityMode.LIFTING])
def test_a_vehicle_that_cannot_lift_is_refused_lifting(tmp_path: Path, mode: ActivityMode) -> None:
    with pytest.raises(DailyOperationValidationError) as refused:
        _create(tmp_path).execute(_command("VT 01", mode))

    assert refused.value.field == "activity_mode"
    assert "VT 01" in refused.value.message


def test_a_crane_may_lift_and_any_vehicle_may_mobilise(tmp_path: Path) -> None:
    create = _create(tmp_path)

    lifted = create.execute(_command("oft tronton", ActivityMode.TRANSPORT))
    crane = create.execute(_command("T CRANE 01", ActivityMode.TRANSPORT_AND_LIFTING))

    assert lifted.activity_mode is ActivityMode.TRANSPORT
    assert crane.activity_mode is ActivityMode.TRANSPORT_AND_LIFTING


def test_a_vehicle_the_catalog_does_not_know_is_not_second_guessed(tmp_path: Path) -> None:
    operation = _create(tmp_path).execute(
        _command("Crane Sewa 01", ActivityMode.TRANSPORT_AND_LIFTING)
    )

    assert operation.activity_mode is ActivityMode.TRANSPORT_AND_LIFTING


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    test_client = TestClient(app)
    test_client.__enter__()
    return test_client


def test_the_form_offers_two_activities_and_names_the_units_that_can_lift(
    client: TestClient,
) -> None:
    page = client.get("/prediksi").text

    activity = page[page.index('id="field-activity_mode"') :]
    activity = activity[: activity.index("</select>")]
    assert re.findall(r'<option value="(\w+)"', activity) == ["transport", "transport_and_lifting"]
    assert "Mobilisasi + lifting" in activity
    assert "data-lifting-vehicles" in page
    for unit in _LIFTING_UNITS:
        assert unit in page


def test_the_api_refuses_lifting_for_a_vehicle_that_cannot_lift(client: TestClient) -> None:
    response = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "vehicle": "VT 05",
            "activity_mode": "transport_and_lifting",
            "lifting_hours": 2,
            "total_distance_km": 20,
            "distance_source": "manual",
        },
    )

    assert response.status_code == 422
    assert "VT 05" in response.text


def test_the_fleet_page_says_which_units_can_lift(client: TestClient) -> None:
    page = client.get("/armada").text

    assert "Lifting" in page
