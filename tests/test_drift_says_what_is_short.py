"""Before drift can be measured, the pages say how much data it needs.

Pergeseran Data said "Belum cukup data" beside tiles counting 12 and 13
operations, without saying what would be enough; Kesehatan Sistem blamed
"prediksi baru" even when the training data was the short side.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_the_pages_name_the_minimum_and_the_short_side(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)  # three rows of history
        _operation_with_prediction(client, 24)
        drift = client.get("/pemantauan/pergeseran-data").text
        health = client.get("/pemantauan/kesehatan-sistem").text

    assert "operasi terkini masing-masing 20 operasi" in drift
    assert (
        "Pergeseran data belum dihitung: baru 3 operasi data latih dan 1 operasi terkini, "
        "masing-masing perlu 20." in health
    )


def test_without_a_model_there_is_nothing_to_compare_against(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        drift = client.get("/pemantauan/pergeseran-data").text
        health = client.get("/pemantauan/kesehatan-sistem").text

    assert "Belum ada model aktif" in drift
    assert "Pergeseran data belum dihitung: belum ada model aktif." in health
