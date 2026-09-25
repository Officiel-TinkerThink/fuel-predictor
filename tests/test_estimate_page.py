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
    assert response.status_code == 201, response.text
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
