"""An estimate can be printed as a fuel slip the code is written on.

The operation code exists to be written down and typed back; until now the
only way to carry it to the fuel point was to copy it by hand. The slip puts
the code, what it stands for and the allocation on paper, with room for the
litres actually used, who recorded them and how they were measured.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.delivery.security import ROUTE_CAPABILITIES
from fuel_predictor.domain.identity import Capability
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline


def test_the_slip_carries_the_code_the_allocation_and_room_for_the_actual(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as client:
        _train_baseline(client)
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "vehicle": "VT 01",
                "activity_mode": "transport",
                "total_distance_km": 45,
                "distance_source": "manual",
            },
        ).json()
        prediction = client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/predictions"
        ).json()
        estimate = client.get(f"/operasi-harian/{operation['operation_id']}").text
        slip = client.get(f"/operasi-harian/{operation['operation_id']}/slip")

    assert f'href="/operasi-harian/{operation["operation_id"]}/slip"' in estimate
    assert slip.status_code == 200
    text = slip.text
    assert operation["operation_code"] in text
    assert "VT 01" in text and "Scania P410 6X6" in text
    # Said once, in the code's legend, not again after the unit's name.
    assert text.count("Scania P410 6X6") == 1
    assert prediction["model"]["model_code"] in text
    assert "BBM aktual terpakai" in text
    assert "window.print" in text or "data-print" in text


def test_a_slip_for_an_operation_without_an_estimate_says_so(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 12,
                "distance_source": "manual",
            },
        ).json()
        slip = client.get(f"/operasi-harian/{operation['operation_id']}/slip")

    assert slip.status_code == 404


def test_the_slip_is_for_whoever_plans() -> None:
    assert ("GET", "/operasi-harian/*/slip", Capability.CREATE_PREDICTION) in ROUTE_CAPABILITIES


def test_a_bulk_result_can_print_every_operations_slip(tmp_path: Path) -> None:
    sheet = (
        "Kategori ANGBER (wajib),Kendaraan (opsional),Mode Aktivitas (wajib),"
        "Jam Lifting (opsional),Jarak Total (km) (wajib),Sumber Jarak (wajib)\n"
        "ANGBER,VT 01,transport,,20,manual\n"
        "ANGBER,VT 05,transport,,25,manual\n"
    )
    app = create_app(
        database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
    )
    with TestClient(app) as client:
        _train_baseline(client)
        page = client.post(
            "/prediksi-operasi-massal",
            files={"file": ("rencana.csv", sheet.encode(), "text/csv")},
        ).text

    batch = page[page.index("data-slip-batch") :]
    assert batch.count('class="slip__sheet"') == 2
    assert "VT-P410-VT01" in batch and "VT-UDQ-VT05" in batch
    assert "data-print-slips" in page
