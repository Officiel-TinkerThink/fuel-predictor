"""Refreshing the page after planning does not plan the operation again.

The estimate was the answer to the form's POST, so a refresh on a phone -
or reopening the tab - asked the browser to send the form again, and a
second operation with its own code (…-2) was planned. Saving now redirects
to the operation's own page, which a refresh simply reloads.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline

_FORM = {"content-type": "application/x-www-form-urlencoded"}
_PLAN = urlencode(
    [
        ("vehicle_category", "ANGBER"),
        ("activity_mode", "transport"),
        ("total_distance_km", "40"),
        ("distance_source", "manual"),
    ]
)


def _waiting(client: TestClient) -> int:
    """Operations planned and waiting for actual fuel, as Catat Aktual lists them."""
    return client.get("/bahan-bakar-aktual").text.count('href="/bahan-bakar-aktual?operation_id=')


def test_saving_redirects_to_the_operation_and_a_refresh_plans_nothing(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        saved = client.post("/operasi-harian", content=_PLAN, headers=_FORM, follow_redirects=False)
        location = saved.headers["location"]
        shown = client.get(location)
        refreshed = client.get(location)
        waiting = _waiting(client)

    assert saved.status_code == 303
    assert location.startswith("/operasi-harian/") and location.endswith("?dibuat=1")
    assert shown.status_code == 200
    assert "Estimasi berhasil dibuat" in shown.text
    assert "Alokasi rekomendasi" in shown.text
    # Reloading reads the same operation; nothing new is planned.
    assert refreshed.status_code == 200
    assert waiting == 1


def test_the_operation_page_without_the_flag_says_nothing_about_creating(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        location = client.post(
            "/operasi-harian", content=_PLAN, headers=_FORM, follow_redirects=False
        ).headers["location"]
        later = client.get(location.split("?")[0])

    assert "Estimasi berhasil dibuat" not in later.text


def test_without_a_model_the_redirected_page_says_why_there_is_no_estimate(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        saved = client.post("/operasi-harian", content=_PLAN, headers=_FORM)

    assert saved.status_code == 200
    assert "Operasi harian tersimpan" in saved.text
    assert "belum ada model aktif" in saved.text.lower()


def test_a_refused_form_is_still_answered_in_place(tmp_path: Path) -> None:
    """Only a saved operation redirects; a form to correct comes back as is."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        refused = client.post(
            "/operasi-harian",
            content=urlencode([("vehicle_category", "ANGBER"), ("distance_source", "manual")]),
            headers=_FORM,
            follow_redirects=False,
        )

    assert refused.status_code == 422
