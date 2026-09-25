"""A person who reaches an address that does not exist gets a page, not JSON.

Any unknown path answered `{"detail":"Not Found"}` - English, raw JSON, no way
back - to someone who had followed an old bookmark or mistyped a link. Pages
now answer with the app's own error page; the API keeps answering JSON, in
the same shape as its other errors.
"""

from pathlib import Path

import pytest
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


def test_an_unexpected_failure_is_a_page_for_a_person_and_json_for_a_program(
    tmp_path: Path,
) -> None:
    """A crash answered "Internal Server Error" in plain English text. A
    browser now gets the app's own page, saying the data is safe and what to
    do; a program gets the API's error shape. The error itself still reaches
    the server, which logs it with its traceback."""
    app = create_app(database_path=tmp_path / "operations.sqlite3")

    def broken() -> None:
        raise RuntimeError("rusak untuk uji")

    app.add_api_route("/rusak", broken)
    app.add_api_route("/api/v1/rusak", broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        page = client.get("/rusak", headers={"accept": "text/html"})
        api = client.get("/api/v1/rusak")

    assert page.status_code == 500
    assert "Terjadi kesalahan" in page.text and "Data yang sudah tersimpan aman" in page.text
    assert "Internal Server Error" not in page.text
    assert api.status_code == 500
    assert api.json()["error"]["code"] == "internal_error"
    assert "rusak untuk uji" not in page.text + api.text
    with (
        TestClient(app) as raising,
        pytest.raises(RuntimeError, match="rusak untuk uji"),
    ):
        raising.get("/rusak", headers={"accept": "text/html"})
