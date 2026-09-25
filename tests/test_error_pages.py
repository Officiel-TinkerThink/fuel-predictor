"""A person who reaches an address that does not exist gets a page, not JSON.

Any unknown path answered `{"detail":"Not Found"}` - English, raw JSON, no way
back - to someone who had followed an old bookmark or mistyped a link. Pages
now answer with the app's own error page; the API keeps answering JSON, in
the same shape as its other errors.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


def test_an_unknown_page_is_a_page_that_leads_back(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.get("/halaman-yang-tidak-ada", headers={"accept": "text/html"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Halaman tidak ditemukan" in response.text
    assert 'href="/"' in response.text


def test_an_unknown_api_address_stays_json(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.get("/api/v1/tidak-ada")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_wrong_method_on_a_page_is_a_page_too(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.put("/prediksi", headers={"accept": "text/html"})

    assert response.status_code == 405
    assert "text/html" in response.headers["content-type"]
