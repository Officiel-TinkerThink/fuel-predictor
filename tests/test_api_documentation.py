"""The API documentation describes the API, not the browser pages.

/docs listed 77 paths, 58 of them the web pages and their form handlers -
noise for anyone integrating, and a map of internal routes. It now lists
what a program talks to: /api/v1, the MCP endpoint, OAuth and its
discovery documents, and the health check.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_FOR_PROGRAMS = ("/api/", "/mcp", "/oauth/", "/.well-known/", "/sehat")


def test_only_what_programs_use_is_documented(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        schema = client.get("/openapi.json").json()

    paths = set(schema["paths"])
    assert paths and all(path.startswith(_FOR_PROGRAMS) for path in paths), sorted(
        path for path in paths if not path.startswith(_FOR_PROGRAMS)
    )
    assert "/api/v1/daily-operations" in paths
    assert "/mcp" in paths
    assert schema["info"]["description"]


def test_the_pages_left_out_of_the_documentation_still_work(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        assert client.get("/prediksi").status_code == 200
        assert client.get("/riwayat-prediksi").status_code == 200
