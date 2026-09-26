"""The estimate page says one number, gives the code, and keeps quiet otherwise.

It opened with two banners (a disclaimer on every visit, and "Jarak manual
dipakai" whenever no route service was configured, though the planner typed
the distance on purpose), then three tiles for one decision, and a red cancel
button louder than anything the planner came for. Now the allocation and the
code sit together at the top, the estimate behind the number is one
sentence, and cancelling is a quiet line at the end.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.application.routing import UnavailableRoutingProvider
from fuel_predictor.infrastructure.packaged_vehicle_catalog import (
    _CATALOG_PATH as _PACKAGED_FLEET,
)
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline
from tests.test_prediction_form_flow import _CATALOG, _FORM, _PreviewOnly


def _plan(client: TestClient, *extra: tuple[str, str]) -> str:
    response = client.post(
        "/operasi-harian",
        content=urlencode(
            [
                ("vehicle_category", "ANGBER"),
                ("vehicle", "Prime Mover"),
                ("activity_mode", "transport"),
                ("total_distance_km", "50"),
                ("distance_source", "manual"),
                *extra,
            ]
        ),
        headers=_FORM,
    )
    assert response.status_code == 200, response.text
    page: str = response.text
    return page


def test_the_allocation_and_the_code_lead_and_cancelling_comes_last(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        page = _plan(client)

    allocation = page.index("allocation-hero")
    code = page.index('class="operation-code"')
    slip = page.index("Cetak slip")
    comparisons = page.index("Operasi serupa sebelumnya")
    cancel = page.index("Salah input atau tercatat dua kali?")
    assert allocation < code < slip < comparisons < cancel
    # The number is explained in one sentence, the caveat said once.
    assert "ditambah cadangan" in page
    assert page.count("bukan konsumsi aktual") == 1
    # The way out of the dialog is not a near-twin of "Batalkan".
    assert ">Kembali</button>" in page and ">Batal</button>" not in page


def test_a_typed_distance_is_not_flagged_when_no_route_service_exists(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "operations.sqlite3", location_catalog=_CATALOG)
    with TestClient(app) as client:
        _train_baseline(client)
        page = _plan(client, ("stop_sequence", "POOL LIMAU"), ("stop_sequence", "KM-001"))

    assert "POOL LIMAU → KM-001" in page
    assert "Jarak manual dipakai" not in page


def test_a_failed_route_service_is_still_flagged(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "operations.sqlite3",
        routing_provider=UnavailableRoutingProvider(),
        route_preview=_PreviewOnly(),
        location_catalog=_CATALOG,
    )
    with TestClient(app) as client:
        _train_baseline(client)
        page = _plan(client, ("stop_sequence", "POOL LIMAU"), ("stop_sequence", "KM-001"))

    assert "Jarak manual dipakai" in page


def test_without_a_model_the_saved_plan_does_not_offer_an_estimate_it_cannot_make(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = _plan(client)

    assert "Belum ada model aktif" in page
    assert "Buat estimasi kebutuhan BBM" not in page
    # The plan is kept, named by its code, and can still be withdrawn.
    assert 'class="operation-code"' in page
    assert "Salah input atau tercatat dua kali?" in page


def _plan_unit(client: TestClient, vehicle: str, distance: str = "50") -> str:
    response = client.post(
        "/operasi-harian",
        content=urlencode(
            [
                ("vehicle_category", "ANGBER"),
                ("vehicle", vehicle),
                ("activity_mode", "transport"),
                ("total_distance_km", distance),
                ("distance_source", "manual"),
            ]
        ),
        headers=_FORM,
    )
    assert response.status_code == 200, response.text
    page: str = response.text
    return page


def test_the_unit_s_type_and_group_are_said_once(tmp_path: Path) -> None:
    """The code's legend says what VT and P410 stand for; the facts below and
    each similar day's unit said the same again after the name."""
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3", vehicle_catalog=PackagedVehicleCatalog()
        )
    ) as client:
        _train_baseline(client)
        # An earlier day on another unit of the same type, shown as similar.
        _plan_unit(client, "VT 02", "48")
        page = _plan_unit(client, "VT 01")

    assert "<strong>P410</strong> = Scania P410 6X6" in page
    assert page.count("Scania P410 6X6") == 1
    assert "VT 02" in page and "Tipe yang sama" in page


def test_a_code_the_fleet_has_since_recoded_keeps_the_type_in_the_facts(tmp_path: Path) -> None:
    """With the unit recoded after the code was issued, the legend no longer
    explains the code and is left out - so the facts still say the type."""
    database = tmp_path / "operations.sqlite3"
    with TestClient(
        create_app(database_path=database, vehicle_catalog=PackagedVehicleCatalog())
    ) as client:
        _train_baseline(client)
        page = _plan_unit(client, "VT 01")
    code = page.split('class="operation-code">', 1)[1].split("<", 1)[0]
    recoded = tmp_path / "armada.csv"
    recoded.write_text(
        _PACKAGED_FLEET.read_text(encoding="utf-8").replace(
            "Scania P410 6X6,P410,", "Scania P410 6X6,S410,"
        ),
        encoding="utf-8",
    )
    with TestClient(
        create_app(database_path=database, vehicle_catalog=PackagedVehicleCatalog(recoded))
    ) as client:
        reopened = client.get(f"/operasi-harian/{code}").text

    assert "-P410-" in code
    assert "operation-code-callout__legend" not in reopened
    assert "Scania P410 6X6" in reopened
