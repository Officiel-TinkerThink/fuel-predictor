"""A person who forgot their password gets a link by email and sets a new one.

Until now the only way back in was an administrator pressing "Atur ulang
kata sandi". Accounts carry an email, so the sign-in page can offer the
usual thing: ask for the username or email, mail a single-use link that
lives thirty minutes, and let the person choose a new password there.

The request page answers the same whether the account exists, has an email,
or not - it never says which. Without an SMTP channel the page says the
feature is off and points at the administrator instead.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")


@dataclass
class _Outbox:
    """Stands in for SMTP: remembers what would have been mailed."""

    sent: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        return True

    def send_reset_link(self, email: str, link: str) -> None:
        self.sent.append((email, link))


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _sign_in(client: TestClient, identifier: str, password: str) -> int:
    page = client.get("/masuk")
    status: int = client.post(
        "/masuk",
        data={"username": identifier, "password": password, "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    ).status_code
    return status


def _sign_out(client: TestClient) -> None:
    client.post("/keluar", data={"csrf_token": _csrf(client.get("/").text)}, follow_redirects=False)


def _with_budi(tmp_path: Path, outbox: _Outbox | None) -> TestClient:
    client = TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            bootstrap_administrator=_ADMIN,
            password_reset_mailer=outbox,
        )
    )
    client.__enter__()
    _sign_in(client, *_ADMIN)
    client.post(
        "/api/v1/users",
        json={
            "username": "budi",
            "full_name": "Budi",
            "email": "budi@example.com",
            "password": "kata-sandi-budi-01",
            "role": "operator",
        },
    )
    _sign_out(client)
    return client


def _request_reset(client: TestClient, identifier: str) -> str:
    page = client.get("/lupa-kata-sandi")
    response = client.post(
        "/lupa-kata-sandi", data={"identifier": identifier, "csrf_token": _csrf(page.text)}
    )
    assert response.status_code == 200, response.text
    text_: str = response.text
    return text_


def _link_token(outbox: _Outbox) -> str:
    (_, link) = outbox.sent[-1]
    match = re.search(r"token=([A-Za-z0-9_-]+)", link)
    assert match, link
    return match.group(1)


def test_the_whole_way_back_in(tmp_path: Path) -> None:
    outbox = _Outbox()
    client = _with_budi(tmp_path, outbox)
    try:
        page = _request_reset(client, "Budi@Example.com")
        assert "tautan" in page.lower()
        assert len(outbox.sent) == 1
        email, link = outbox.sent[0]
        assert email == "budi@example.com"
        assert link.startswith("http://testserver/atur-ulang-kata-sandi?token=")
        token = _link_token(outbox)

        form = client.get(f"/atur-ulang-kata-sandi?token={token}")
        assert form.status_code == 200
        assert 'name="new_password"' in form.text
        done = client.post(
            "/atur-ulang-kata-sandi",
            data={
                "token": token,
                "new_password": "kata-sandi-baru-99",
                "csrf_token": _csrf(form.text),
            },
            follow_redirects=False,
        )
        assert done.status_code == 303
        assert done.headers["location"].startswith("/masuk")

        assert _sign_in(client, "budi", "kata-sandi-budi-01") == 401
        assert _sign_in(client, "budi", "kata-sandi-baru-99") == 303
    finally:
        client.__exit__(None, None, None)


def test_the_request_page_never_says_whether_an_account_exists(tmp_path: Path) -> None:
    outbox = _Outbox()
    client = _with_budi(tmp_path, outbox)
    try:
        known = _request_reset(client, "budi")
        unknown = _request_reset(client, "tidak-ada")
        no_email = _request_reset(client, "admin")
    finally:
        client.__exit__(None, None, None)

    # One mail went out (budi has an address); every answer reads the same.
    assert len(outbox.sent) == 1
    for page in (known, unknown, no_email):
        assert "Jika akun itu punya email" in page
    assert "tidak ditemukan" not in unknown.lower()


def test_a_link_is_single_use_and_expires(tmp_path: Path) -> None:
    outbox = _Outbox()
    client = _with_budi(tmp_path, outbox)
    try:
        _request_reset(client, "budi@example.com")
        token = _link_token(outbox)
        form = client.get(f"/atur-ulang-kata-sandi?token={token}")
        client.post(
            "/atur-ulang-kata-sandi",
            data={
                "token": token,
                "new_password": "kata-sandi-baru-99",
                "csrf_token": _csrf(form.text),
            },
        )
        second = client.get(f"/atur-ulang-kata-sandi?token={token}")
        assert second.status_code == 410
        assert "tidak berlaku" in second.text.lower()

        _request_reset(client, "budi@example.com")
        stale = _link_token(outbox)
        with create_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'operations.sqlite3').as_posix()}"
        ).begin() as db:
            db.execute(
                text("UPDATE password_reset_tokens SET expires_at = :at"),
                {"at": datetime.now(UTC) - timedelta(minutes=1)},
            )
        expired = client.get(f"/atur-ulang-kata-sandi?token={stale}")
        assert expired.status_code == 410
        garbage = client.get("/atur-ulang-kata-sandi?token=bukan-token")
        assert garbage.status_code == 410
    finally:
        client.__exit__(None, None, None)


def test_requests_for_one_account_are_throttled(tmp_path: Path) -> None:
    outbox = _Outbox()
    client = _with_budi(tmp_path, outbox)
    try:
        for _ in range(5):
            _request_reset(client, "budi@example.com")
    finally:
        client.__exit__(None, None, None)

    # Three within the window are honoured; the rest answer the same but send nothing.
    assert len(outbox.sent) == 3


def test_without_a_mail_channel_the_page_points_at_the_administrator(tmp_path: Path) -> None:
    client = _with_budi(tmp_path, None)
    try:
        page = client.get("/lupa-kata-sandi")
        sign_in = client.get("/masuk")
    finally:
        client.__exit__(None, None, None)

    assert page.status_code == 200
    assert "administrator" in page.text.lower()
    assert 'name="identifier"' not in page.text
    # The sign-in page still offers the way there.
    assert 'href="/lupa-kata-sandi"' in sign_in.text


def test_the_sign_in_page_links_to_it(tmp_path: Path) -> None:
    client = _with_budi(tmp_path, _Outbox())
    try:
        page = client.get("/masuk").text
    finally:
        client.__exit__(None, None, None)

    assert 'href="/lupa-kata-sandi"' in page
