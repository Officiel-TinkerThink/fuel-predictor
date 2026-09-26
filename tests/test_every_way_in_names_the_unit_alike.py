"""However an operation arrives, its unit is stored under the fleet's name.

The web form offers a dropdown and an agent's words were resolved against
the fleet, but the REST API and the plan sheet stored the unit as written:
"t crane 01" and "PM 01" became units of their own, which the model had
never seen. `CreateDailyOperation` now resolves the unit itself, so every
way in agrees; a unit the fleet does not know - a rented crane - is still
planned under the name it was given.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
        )
    )


def _plan(client: TestClient, vehicle: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "vehicle": vehicle,
            "activity_mode": "transport",
            "total_distance_km": 30,
            "distance_source": "manual",
        },
    )
    body: dict[str, object] = {"status": response.status_code, **response.json()}
    return body


def test_the_api_stores_a_loosely_written_unit_under_its_fleet_name(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        crane = _plan(client, "t crane 01")
        mover = _plan(client, "PM 01")

    assert crane["status"] == 201 and crane["vehicle"] == "Truck Crane 01"
    assert mover["status"] == 201 and mover["vehicle"] == "Prime Mover"


def test_the_api_plans_a_unit_the_fleet_does_not_know_under_its_own_name(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        rented = _plan(client, "Crane Sewa 01")

    assert rented["status"] == 201 and rented["vehicle"] == "Crane Sewa 01"


def test_without_a_fleet_on_record_the_unit_is_taken_as_written(tmp_path: Path) -> None:
    """A database whose fleet has not been imported yet still plans."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        planned = _plan(client, "Truk Baru")

    assert planned["status"] == 201 and planned["vehicle"] == "Truk Baru"
