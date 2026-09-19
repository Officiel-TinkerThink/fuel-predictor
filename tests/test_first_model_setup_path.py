"""The way to a first model is visible, not a URL to know.

Importing history and training a baseline is how a fresh installation gets
its first model, and the page for it (/impor-data-historis) was reachable
only by typing the address: no menu entry, no link from the overview that
said "no active model", none from the empty candidate list. The steps are
now signposted from all three places.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline


def test_the_import_page_is_in_the_navigation(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/prediksi")

    assert 'href="/impor-data-historis"' in page.text
    assert "Impor Data Historis" in page.text


def test_the_overview_walks_through_the_setup_when_no_model_is_active(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        before = client.get("/")
        _train_baseline(client)
        after = client.get("/")

    assert "Siapkan model pertama" in before.text
    assert 'href="/impor-data-historis"' in before.text
    assert "Siapkan model pertama" not in after.text


def test_the_empty_candidate_list_points_at_the_import(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/pengelolaan-model")

    assert 'href="/impor-data-historis"' in page.text
