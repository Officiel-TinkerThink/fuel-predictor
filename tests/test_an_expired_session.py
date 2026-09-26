"""A session that ended while a form was open leads back to sign-in, plainly.

Submitting a form after the session had expired answered "Akses ditolak":
the forgery check ran first and, with no session to compare against,
refused the request as if it were an attack - a message about permissions
for what was only an expired sign-in. Now a request without a session that
needs one is sent to sign in, told why, and returned to the page the form
was on (not to the address the form posted to, which has no page).
"""

from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_two_roles import _ADMIN, _csrf, _sign_in

_PLAN = {
    "vehicle_category": "ANGBER",
    "activity_mode": "transport",
    "total_distance_km": "40",
    "distance_source": "manual",
}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )


def test_a_form_sent_after_the_session_ended_asks_to_sign_in_again(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        token = _csrf(client.get("/prediksi").text)
        client.cookies.delete("fp_session")
        sent = client.post(
            "/operasi-harian",
            data={**_PLAN, "csrf_token": token},
            headers={"referer": "http://testserver/prediksi"},
            follow_redirects=False,
        )
        sign_in = client.get(sent.headers["location"])

    assert sent.status_code == 303
    location = unquote(sent.headers["location"])
    assert location.startswith("/masuk?")
    # Back to the form's own page afterwards, not to the address it posted to.
    assert "tujuan=/prediksi" in location
    assert "Sesi Anda sudah berakhir" in sign_in.text
    assert 'class="banner banner--warning"' in sign_in.text
    assert "Akses ditolak" not in sign_in.text


def test_a_referrer_from_elsewhere_is_not_followed(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        sent = client.post(
            "/operasi-harian",
            data=_PLAN,
            headers={"referer": "https://penyerang.example/jebakan"},
            follow_redirects=False,
        )

    assert sent.status_code == 303
    assert "penyerang" not in unquote(sent.headers["location"])


def test_nothing_is_done_for_a_request_without_a_session(tmp_path: Path) -> None:
    """Sent to sign in before anything runs - no operation is planned."""
    with _client(tmp_path) as client:
        client.post("/operasi-harian", data=_PLAN, follow_redirects=False)
        _sign_in(client, *_ADMIN)
        waiting = client.get("/bahan-bakar-aktual").text

    assert 'href="/bahan-bakar-aktual?operation_id=' not in waiting


def test_a_public_form_still_needs_its_token(tmp_path: Path) -> None:
    """The sign-in form has no session to lean on; its own token still guards it."""
    with _client(tmp_path) as client:
        forged = client.post(
            "/masuk", data={"username": _ADMIN[0], "password": _ADMIN[1]}, follow_redirects=False
        )

    assert forged.status_code == 403


def test_a_signed_in_form_without_its_token_is_still_refused(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _sign_in(client, *_ADMIN)
        forged = client.post("/operasi-harian", data=_PLAN, follow_redirects=False)

    assert forged.status_code == 403


def test_good_news_on_the_sign_in_page_stays_green(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        changed = client.get("/masuk?pesan=kata-sandi").text
        unknown = client.get("/masuk?pesan=apa-saja").text

    assert 'class="banner banner--success"' in changed
    assert "Kata sandi Anda sudah diubah" in changed
    assert 'class="banner' not in unknown
