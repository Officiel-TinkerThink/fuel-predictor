"""Agen Saya and Integrasi Agen let a connection be named and, once dead, removed.

The pages could revoke a grant and nothing else: a person with two "Claude
Code" connections could not tell them apart, and revoked rows stayed in the
list forever. Each row now has "Beri nama" (a label of the person's own; the
client's name stays visible beneath it) and, once the grant is revoked,
"Hapus" to take it off the list. Administrators get the same on their page.
"""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from tests.test_oauth_mcp_connection import (
    _ADMIN,
    _app,
    _consent,
    _csrf_token,
    _redeem,
    _register,
    _sign_in,
)


def _connected_admin(tmp_path: Path) -> TestClient:
    """An administrator signed in with one agent connected through OAuth."""
    client = _app(tmp_path)
    _sign_in(client, *_ADMIN)
    client_id = _register(client)
    location = _consent(client, client_id)
    code = parse_qs(urlsplit(location).query)["code"][0]
    _redeem(client, client_id, code)
    return client


def _csrf(html: str) -> str:
    return _csrf_token(html)


def _grant_id(page: str) -> str:
    marker = 'action="/agen-saya/'
    start = page.index(marker) + len(marker)
    return page[start : page.index("/", start)]


def test_a_connection_can_be_named_then_revoked_then_removed(tmp_path: Path) -> None:
    client = _connected_admin(tmp_path)
    try:
        page = client.get("/agen-saya").text
        grant_id = _grant_id(page)
        token = _csrf(page)
        assert "Beri nama" in page
        assert 'action="/agen-saya/' + grant_id + '/hapus"' not in page  # still active

        named = client.post(
            f"/agen-saya/{grant_id}/nama",
            data={"label": "Laptop kantor", "csrf_token": token},
            follow_redirects=False,
        )
        page = client.get("/agen-saya").text
        assert named.status_code == 303
        assert "Laptop kantor" in page

        client.post(f"/agen-saya/{grant_id}/cabut", data={"csrf_token": token})
        page = client.get("/agen-saya").text
        assert f'action="/agen-saya/{grant_id}/hapus"' in page

        removed = client.post(
            f"/agen-saya/{grant_id}/hapus", data={"csrf_token": token}, follow_redirects=False
        )
        page = client.get("/agen-saya").text
        assert removed.status_code == 303
        assert grant_id not in page
    finally:
        client.__exit__(None, None, None)


def test_the_administrator_page_offers_the_same_actions(tmp_path: Path) -> None:
    client = _connected_admin(tmp_path)
    try:
        page = client.get("/integrasi-agen").text
        marker = 'action="/integrasi-agen/grant/'
        start = page.index(marker) + len(marker)
        grant_id = page[start : page.index("/", start)]
        token = _csrf(page)

        renamed = client.post(
            f"/integrasi-agen/grant/{grant_id}/nama",
            data={"label": "Agen tim rute", "csrf_token": token},
            follow_redirects=False,
        )
        client.post(f"/integrasi-agen/grant/{grant_id}/cabut", data={"csrf_token": token})
        page = client.get("/integrasi-agen").text
        removed = client.post(
            f"/integrasi-agen/grant/{grant_id}/hapus",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        after = client.get("/integrasi-agen").text

        assert renamed.status_code == 303
        assert "Agen tim rute" in page
        assert f'action="/integrasi-agen/grant/{grant_id}/hapus"' in page
        assert removed.status_code == 303
        assert grant_id not in after
    finally:
        client.__exit__(None, None, None)
