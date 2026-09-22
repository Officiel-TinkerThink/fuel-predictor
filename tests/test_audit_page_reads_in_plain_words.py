"""The audit page names actions in words and shows what was recorded.

Rows read "sign_in_failed" and "mcp_tool:predict_fuel", and the details each
record carried - the reason a sign-in failed, the note an agent call left -
were never rendered at all. A manager reading the page saw codes and had to
guess. Each action now has a label, the actor's kind is shown, details are
listed under the row, and the outcome can be narrowed to failures.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def test_actions_are_labelled_and_details_shown(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    with TestClient(app) as client:
        sign_in = client.get("/masuk")
        client.post(
            "/masuk",
            data={"username": "admin", "password": "salah", "csrf_token": _csrf(sign_in.text)},
        )
        client.post(
            "/masuk",
            data={"username": _ADMIN[0], "password": _ADMIN[1], "csrf_token": _csrf(sign_in.text)},
        )
        page = client.get("/audit")

    assert page.status_code == 200
    assert "Masuk gagal" in page.text
    # The successful sign-in that followed is not in the trail at all.
    assert "Masuk berhasil" not in page.text and "sign_in_succeeded" not in page.text
    # The raw code stays available for anyone grepping a log against the page.
    assert "sign_in_failed" in page.text
    # A filter on outcome, so failures can be read on their own.
    assert 'data-filter-attribute="data-outcome"' in page.text
    assert 'data-outcome="failed"' in page.text
