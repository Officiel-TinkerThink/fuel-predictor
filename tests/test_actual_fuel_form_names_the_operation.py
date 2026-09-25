"""Before saving actual fuel, the form says which operation it will be saved to.

A code alone gave no sign of a typo or a wrong row. When the code (from a
"Catat" link, or typed - app.js does the same live) matches an operation still
waiting, the form names its vehicle, when it was predicted and its allocation;
app.js also warns, without blocking, when the litres are far from that
allocation.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline


def _plan(client: TestClient) -> dict[str, str]:
    operation: dict[str, str] = client.post(
        "/api/v1/daily-operations",
        json={
            "vehicle_category": "ANGBER",
            "activity_mode": "transport",
            "total_distance_km": 24,
            "distance_source": "manual",
        },
    ).json()
    client.post(f"/api/v1/daily-operations/{operation['operation_id']}/predictions")
    return operation


def test_a_linked_code_names_the_operation_it_will_be_saved_to(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _plan(client)

        page = client.get(f"/bahan-bakar-aktual?operation_id={operation['operation_code']}").text

    box = page[page.index("data-chosen-operation") : page.index("data-code-not-waiting")]
    assert " hidden" not in box.split(">", 1)[0]
    assert "Operasi yang akan dicatat" in box
    assert "alokasi" in box


def test_without_a_code_nothing_is_named_yet(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        _plan(client)

        page = client.get("/bahan-bakar-aktual").text

    assert "data-chosen-operation hidden" in page
    # Every waiting row carries what the live check needs.
    assert "data-ref-id=" in page and "data-allocation=" in page
