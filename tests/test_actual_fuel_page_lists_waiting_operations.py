"""The actual-fuel page offers the operations still waiting, instead of
demanding a 36-character ID from memory.

The only way to record actual fuel used to be to type the OPR-… id by hand.
Nobody remembers one, so in practice people copied it from somewhere else or
gave up, and the model never learned from the day. The page now lists the
predicted operations that have no actual record yet, newest first, and a
"Catat" link pre-fills the form with the chosen id.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_page_lists_predicted_operations_without_actual_fuel_newest_first(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        older = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        newer = _operation_with_prediction(client, 36)["operation"]["operation_id"]

        page = client.get("/bahan-bakar-aktual").text

    assert page.index(newer) < page.index(older)
    assert f'href="/bahan-bakar-aktual?operation_id={newer}"' in page


def test_an_operation_leaves_the_list_once_its_actual_fuel_is_recorded(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        done = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        waiting = _operation_with_prediction(client, 36)["operation"]["operation_id"]
        client.post(
            f"/api/v1/daily-operations/{done}/actual-fuel",
            json={"actual_fuel_liters": 20, "measurement_source": "fuel_meter"},
        )

        page = client.get("/bahan-bakar-aktual").text

    assert waiting in page
    assert done not in page


def test_an_operation_without_a_prediction_is_not_offered(tmp_path: Path) -> None:
    """There is nothing to compare an actual against until a prediction exists."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        unpredicted = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 12,
                "distance_source": "manual",
            },
        ).json()["operation_id"]

        page = client.get("/bahan-bakar-aktual").text

    assert unpredicted not in page


def test_choosing_an_operation_prefills_the_form(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        chosen = _operation_with_prediction(client, 24)["operation"]["operation_id"]

        page = client.get(f"/bahan-bakar-aktual?operation_id={chosen}").text

    assert f'name="operation_id" type="text" value="{chosen}"' in page


def test_the_page_says_so_when_nothing_is_waiting(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/bahan-bakar-aktual").text

    assert "Semua prediksi sudah punya BBM aktual" in page


def test_waiting_list_does_not_drop_operations_after_twenty(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        ids = [
            _operation_with_prediction(client, 20 + index)["operation"]["operation_id"]
            for index in range(21)
        ]
        page = client.get("/bahan-bakar-aktual").text

    for operation_id in ids:
        assert f'href="/bahan-bakar-aktual?operation_id={operation_id}"' in page
    assert 'data-list-label="Menunggu BBM aktual"' in page
