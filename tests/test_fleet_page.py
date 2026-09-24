"""Anyone who plans or records fuel can see the fleet's taxonomy and codes.

A vehicle code - `VT-P410-VT01` - is only easy to trust if the people writing
it down can check it. The Armada page lists every unit with its code, group and
type; the code on an estimate explains its own parts.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app
from tests.test_two_roles import _ADMIN, _OPERATOR, _sign_in, _sign_out


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as test_client:
        yield test_client


def test_the_fleet_page_lists_every_unit_with_its_code_group_and_type(
    client: TestClient,
) -> None:
    page = client.get("/armada")

    assert page.status_code == 200
    for expected in (
        "VT-P410-VT01",
        "Scania P410 6X6",
        "VT-UDQ-VT05",
        "UD Truck Quester CWE 280 64R",
        "TR-HINO-OFT",
        "Oil Field Truck",
        # The other spellings, so a name from a sheet can be traced to its unit.
        "OFT Tronton",
        "VT-VT14",
    ):
        assert expected in page.text, expected


def test_the_fleet_page_explains_how_a_code_reads(client: TestClient) -> None:
    page = client.get("/armada").text

    assert "Vacuum Truck" in page
    assert "260924-0914-VT-P410-VT01" in page


def test_an_operator_can_open_the_fleet_page_from_the_navigation(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3",
        bootstrap_administrator=_ADMIN,
        vehicle_catalog=PackagedVehicleCatalog(),
    )
    with TestClient(app) as admin:
        _sign_in(admin, *_ADMIN)
        admin.post(
            "/api/v1/users",
            json={
                "username": _OPERATOR[0],
                "full_name": "Andi",
                "password": _OPERATOR[1],
                "role": "operator",
            },
        )
        _sign_out(admin)
        _sign_in(admin, *_OPERATOR)

        overview = admin.get("/").text
        page = admin.get("/armada")

    assert 'href="/armada"' in overview
    assert page.status_code == 200


def test_the_code_on_a_saved_operation_names_its_parts(client: TestClient) -> None:
    operation = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "vehicle": "VT 01",
            "activity_mode": "transport",
            "total_distance_km": 12,
            "distance_source": "manual",
        },
    ).json()

    html = client.get(f"/operasi-harian/{operation['operation_id']}").text
    page = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))

    assert operation["operation_code"].endswith("-VT-P410-VT01")
    assert "VT = Vacuum Truck" in page
    assert "P410 = Scania P410 6X6" in page
    assert "VT01 = VT 01" in page
    assert 'href="/armada"' in html
