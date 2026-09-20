"""The prediction form: pick stops by typing, get the estimate in one step.

Two things made the most-used screen harder than it needed to be. The stop
pickers were <select>s holding the whole location catalogue - over a thousand
names on the real fleet - so finding "POOL LIMAU" meant scrolling. And saving
an operation landed on a summary page whose only purpose was a second button
that produced the estimate the planner came for.

Now each stop is a text input backed by one shared <datalist>, so typing
filters, and a typed name is resolved against the catalogue the same tolerant
way an agent's request is (case, spacing). Saving goes straight to the
estimate whenever a model is active; without one, the saved-operation page
still says so.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from httpx import Response

from fuel_predictor.application.locations import LocationOption
from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline
from tests.test_ordered_route_calculation import FakeLocationCatalog, RecordingRoutingProvider

_FORM = {"content-type": "application/x-www-form-urlencoded"}
_CATALOG = FakeLocationCatalog(
    (
        LocationOption(name="POOL LIMAU", latitude=-3.1, longitude=104.2),
        LocationOption(name="KM-001", latitude=-3.2, longitude=104.3),
        LocationOption(name="KM-002", latitude=-3.3, longitude=104.4),
    )
)


def _post_operation(client: TestClient, *stops: str) -> Response:
    response: Response = client.post(
        "/operasi-harian",
        content=urlencode(
            [
                ("vehicle_category", "ANGBER"),
                ("activity_mode", "transport"),
                ("total_distance_km", "50"),
                ("distance_source", "manual"),
                *(("stop_sequence", stop) for stop in stops),
            ]
        ),
        headers=_FORM,
    )
    return response


def test_stops_are_typed_against_one_shared_datalist(tmp_path: Path) -> None:
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", location_catalog=_CATALOG)
    ) as client:
        form = client.get("/prediksi").text

    assert 'list="katalog-lokasi"' in form
    assert form.count('<datalist id="katalog-lokasi">') == 1
    assert '<option value="POOL LIMAU"' in form
    # The catalogue is not repeated per stop row.
    assert form.count('value="POOL LIMAU"') == 1


def test_a_typed_stop_is_resolved_to_its_catalogued_spelling(tmp_path: Path) -> None:
    provider = RecordingRoutingProvider(distance_km=15)
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            routing_provider=provider,
            location_catalog=_CATALOG,
        )
    ) as client:
        response = _post_operation(client, "pool limau", "km 001")

    assert response.status_code == 201, response.text
    assert provider.submitted_sequences == [("POOL LIMAU", "KM-001")]


def test_an_unknown_stop_is_refused_with_the_closest_names(tmp_path: Path) -> None:
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", location_catalog=_CATALOG)
    ) as client:
        response = _post_operation(client, "POOL LIMAU", "KM-00")

    assert response.status_code == 422
    text = response.text
    assert "KM-00" in text
    assert "KM-001" in text and "KM-002" in text
    # The typed value survives so the planner can correct it rather than retype.
    assert 'value="KM-00"' in text
    assert 'href="#field-stop_sequence"' in text


def test_saving_an_operation_goes_straight_to_the_estimate_when_a_model_is_active(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        response = _post_operation(client)

    assert response.status_code == 201
    text = response.text
    assert "Estimasi kebutuhan bahan bakar" in text
    assert "Alokasi rekomendasi" in text
    # The operation the estimate was made for is still readable on the page.
    assert "50 km" in text


def test_saving_without_an_active_model_still_records_the_operation_and_says_why(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = _post_operation(client)

    assert response.status_code == 201
    text = response.text
    assert "Operasi harian tersimpan" in text
    assert "belum ada model aktif" in text.lower()
