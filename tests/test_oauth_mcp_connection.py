"""Connecting a coding agent to `/mcp` the way the MCP specification says (ADR 0014).

Played from both sides. The *client* side is what Claude Code or Cursor does
with no credential configured: hit `/mcp`, read the challenge, follow the
discovery documents, register, send the person to the browser, redeem the
code with PKCE, and present the token. The *person* side is the sign-in and
consent page, then the "Agen Saya" page where they see and cut off what they
connected.
"""

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi.testclient import TestClient

from fuel_predictor.domain.agent_authorization import code_challenge_for
from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")
_OPERATOR = ("andi", "kata-sandi-andi-01")
_REDIRECT = "http://127.0.0.1:52341/callback"
_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"


def _app(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN),
        base_url="https://fuel.example",
    )
    client.__enter__()
    return client


def _csrf_token(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _sign_in(client: TestClient, username: str, password: str, destination: str = "/") -> None:
    page = client.get("/masuk")
    response = client.post(
        "/masuk",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf_token(page.text),
            "tujuan": destination,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def _sign_out(client: TestClient) -> None:
    page = client.get("/")
    client.post("/keluar", data={"csrf_token": _csrf_token(page.text)}, follow_redirects=False)


def _add_operator(client: TestClient) -> None:
    _sign_in(client, *_ADMIN)
    page = client.get("/pengguna")
    response = client.post(
        "/pengguna",
        data={
            "username": _OPERATOR[0],
            "full_name": "Andi Operator",
            "password": _OPERATOR[1],
            "role": "operator",
            "csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 201, 303), response.text
    _sign_out(client)


def _register(client: TestClient, name: str = "Claude Code") -> str:
    response = client.post(
        "/oauth/register", json={"client_name": name, "redirect_uris": [_REDIRECT]}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_endpoint_auth_method"] == "none"
    client_id: str = body["client_id"]
    return client_id


def _authorize_url(client_id: str, **overrides: str) -> str:
    parameters = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _REDIRECT,
        "code_challenge": code_challenge_for(_VERIFIER),
        "code_challenge_method": "S256",
        "scope": "fuel:predict fuel:monitor",
        "state": "state-123",
        "resource": "https://fuel.example/mcp",
    }
    parameters.update(overrides)
    return f"/oauth/authorize?{urlencode(parameters)}"


def _consent(client: TestClient, client_id: str, *, decision: str = "izinkan") -> str:
    """Submit the consent form as the signed-in person; returns the redirect Location."""
    page = client.get(_authorize_url(client_id))
    assert page.status_code == 200, page.text
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page.text))
    scopes = re.findall(r'name="scopes" value="([^"]+)"', page.text)
    response = client.post(
        "/oauth/authorize",
        data={**fields, "scopes": scopes, "decision": decision},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return str(response.headers["location"])


def _redeem(client: TestClient, client_id: str, code: str) -> dict[str, Any]:
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": _REDIRECT,
            "code_verifier": _VERIFIER,
            "resource": "https://fuel.example/mcp",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body: dict[str, Any] = response.json()
    return body


def _mcp(client: TestClient, token: str | None, body: dict[str, Any]) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/mcp", json=body, headers=headers)


# --- discovery ------------------------------------------------------------------


def test_an_unauthenticated_mcp_call_points_at_the_discovery_document(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        challenge = _mcp(client, None, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert challenge.status_code == 401
        www = challenge.headers["www-authenticate"]
        assert (
            'resource_metadata="https://fuel.example/.well-known/oauth-protected-resource"' in www
        )

        resource = client.get("/.well-known/oauth-protected-resource").json()
        assert resource["resource"] == "https://fuel.example/mcp"
        assert resource["authorization_servers"] == ["https://fuel.example"]
        # The path-suffixed form a client derives from the MCP URL itself.
        assert client.get("/.well-known/oauth-protected-resource/mcp").json() == resource

        server = client.get("/.well-known/oauth-authorization-server").json()
        assert server["issuer"] == "https://fuel.example"
        assert server["authorization_endpoint"] == "https://fuel.example/oauth/authorize"
        assert server["token_endpoint"] == "https://fuel.example/oauth/token"
        assert server["registration_endpoint"] == "https://fuel.example/oauth/register"
        assert server["code_challenge_methods_supported"] == ["S256"]
        assert server["token_endpoint_auth_methods_supported"] == ["none"]
        assert client.get("/.well-known/openid-configuration").json() == server


def test_a_configured_public_url_wins_over_the_scheme_the_proxy_chain_leaks(
    tmp_path: Path,
) -> None:
    """In production a CDN talks plain HTTP to the gateway, so the app sees http://
    and, left to the request, would advertise http:// endpoints and a `resource`
    it then refuses. The configured origin is what the client actually sees."""
    app = create_app(
        database_path=tmp_path / "operations.sqlite3",
        bootstrap_administrator=_ADMIN,
        public_url="https://fuel.example",
    )
    with TestClient(app, base_url="http://app:8000") as client:
        www = _mcp(client, None, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}).headers[
            "www-authenticate"
        ]
        assert 'resource_metadata="https://fuel.example/.well-known/' in www
        resource = client.get("/.well-known/oauth-protected-resource").json()
        assert resource["resource"] == "https://fuel.example/mcp"
        assert resource["authorization_servers"] == ["https://fuel.example"]
        server = client.get("/.well-known/oauth-authorization-server").json()
        assert server["issuer"] == "https://fuel.example"
        assert server["registration_endpoint"] == "https://fuel.example/oauth/register"

        # And the https resource a client copies from that document is accepted:
        # the anonymous authorize request is sent to sign in, not bounced with
        # an invalid_target error, and the whole flow completes.
        _add_operator(client)
        client_id = _register(client)
        anonymous = client.get(_authorize_url(client_id), follow_redirects=False)
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/masuk")
        _sign_in(client, *_OPERATOR)
        location = _consent(client, client_id)
        code = parse_qs(urlsplit(location).query)["code"][0]
        tokens = _redeem(client, client_id, code)
        listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        listed = _mcp(client, tokens["access_token"], listing)
        assert listed.status_code == 200, listed.text


def test_registration_refuses_unsafe_redirects_and_malformed_bodies(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        unsafe = client.post(
            "/oauth/register",
            json={"client_name": "Evil", "redirect_uris": ["http://evil.example/cb"]},
        )
        assert unsafe.status_code == 400
        assert unsafe.json()["error"] == "invalid_redirect_uri"

        malformed = client.post("/oauth/register", content=b"not json")
        assert malformed.status_code == 400
        assert malformed.json()["error"] == "invalid_client_metadata"


# --- the whole flow ---------------------------------------------------------------


def test_a_planner_connects_their_agent_and_it_acts_as_them(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)

        # Without a session the browser is sent to sign in, and the whole
        # authorization request survives the round trip.
        anonymous = client.get(_authorize_url(client_id), follow_redirects=False)
        assert anonymous.status_code == 303
        destination = parse_qs(urlsplit(anonymous.headers["location"]).query)["tujuan"][0]
        assert destination.startswith("/oauth/authorize?")
        assert "code_challenge=" in destination

        _sign_in(client, *_OPERATOR, destination=destination)
        page = client.get(_authorize_url(client_id))
        assert "Claude Code" in page.text
        assert "127.0.0.1:52341" in page.text
        assert "Izinkan" in page.text

        location = _consent(client, client_id)
        assert location.startswith(f"{_REDIRECT}?")
        query = parse_qs(urlsplit(location).query)
        assert query["state"] == ["state-123"]
        (code,) = query["code"]

        tokens = _redeem(client, client_id, code)
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 3600
        assert tokens["scope"] == "fuel:monitor fuel:predict"

        listed = _mcp(
            client, tokens["access_token"], {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert listed.status_code == 200
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert "predict_fuel" in names
        assert "get_service_health" in names
        assert "get_current_model" not in names, "models:read was not requested"

        # A tool call is audited as the planner's agent, by name.
        called = _mcp(
            client,
            tokens["access_token"],
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_service_health"},
            },
        )
        assert called.status_code == 200
        _sign_in(client, *_ADMIN)
        assert "andi via Claude Code" in client.get("/audit").text


def test_refreshing_keeps_the_agent_connected_after_the_access_token_expires(
    tmp_path: Path,
) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)
        code = parse_qs(urlsplit(_consent(client, client_id)).query)["code"][0]
        first = _redeem(client, client_id, code)

        refreshed = client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        second = refreshed.json()
        assert second["access_token"] != first["access_token"]
        assert (
            _mcp(
                client, second["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            ).status_code
            == 200
        )

        replayed = client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
        assert replayed.status_code == 400
        assert replayed.json()["error"] == "invalid_grant"
        # Replay revoked the grant; the newer token is dead too.
        assert (
            _mcp(
                client, second["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            ).status_code
            == 401
        )


def test_declining_sends_the_agent_an_access_denied_error(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)
        location = _consent(client, client_id, decision="tolak")
        query = parse_qs(urlsplit(location).query)
        assert query["error"] == ["access_denied"]
        assert query["state"] == ["state-123"]


def test_a_wrong_verifier_or_unknown_grant_type_is_refused(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)
        code = parse_qs(urlsplit(_consent(client, client_id)).query)["code"][0]

        wrong = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": _REDIRECT,
                "code_verifier": "b" * 43,
            },
        )
        assert wrong.status_code == 400
        assert wrong.json()["error"] == "invalid_grant"

        unknown = client.post("/oauth/token", data={"grant_type": "password"})
        assert unknown.status_code == 400
        assert unknown.json()["error"] == "unsupported_grant_type"


def test_a_bad_client_is_shown_an_error_here_never_redirected(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)

        unknown_client = client.get(_authorize_url("REG-nope"), follow_redirects=False)
        assert unknown_client.status_code == 400
        assert "tidak dapat diproses" in unknown_client.text

        wrong_redirect = client.get(
            _authorize_url(client_id, redirect_uri="http://127.0.0.1:52341/elsewhere"),
            follow_redirects=False,
        )
        assert wrong_redirect.status_code == 400

        # But a fault after that is the client's to hear about, at its redirect.
        no_pkce = client.get(_authorize_url(client_id, code_challenge=""), follow_redirects=False)
        assert no_pkce.status_code == 303
        assert parse_qs(urlsplit(no_pkce.headers["location"]).query)["error"] == ["invalid_request"]


# --- the pages ----------------------------------------------------------------------


def test_agen_saya_lists_the_grant_and_revoking_it_cuts_the_agent_off(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)
        code = parse_qs(urlsplit(_consent(client, client_id)).query)["code"][0]
        tokens = _redeem(client, client_id, code)

        page = client.get("/agen-saya")
        assert page.status_code == 200
        assert "Claude Code" in page.text
        assert "https://fuel.example/mcp" in page.text
        grant_id = page.text.split('action="/agen-saya/')[1].split("/cabut")[0]

        revoked = client.post(
            f"/agen-saya/{grant_id}/cabut", data={"csrf_token": _csrf_token(page.text)}
        )
        assert revoked.status_code == 200
        assert "Dicabut" in revoked.text
        assert (
            _mcp(
                client, tokens["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            ).status_code
            == 401
        )


def test_an_administrator_sees_every_users_agents_and_can_revoke_them(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        _add_operator(client)
        client_id = _register(client)
        _sign_in(client, *_OPERATOR)
        code = parse_qs(urlsplit(_consent(client, client_id)).query)["code"][0]
        tokens = _redeem(client, client_id, code)
        _sign_out(client)

        _sign_in(client, *_ADMIN)
        page = client.get("/integrasi-agen")
        assert "Andi Operator" in page.text
        assert "Claude Code" in page.text
        grant_id = page.text.split('action="/integrasi-agen/grant/')[1].split("/cabut")[0]
        revoked = client.post(
            f"/integrasi-agen/grant/{grant_id}/cabut",
            data={"csrf_token": _csrf_token(page.text)},
        )
        assert revoked.status_code == 200
        assert (
            _mcp(
                client, tokens["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            ).status_code
            == 401
        )


def test_the_consent_page_needs_a_real_account(tmp_path: Path) -> None:
    """In unprovisioned local mode there is nobody to delegate from."""
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", allow_unprovisioned_access=True)
    ) as client:
        client_id = _register(client)
        page = client.get(_authorize_url(client_id), follow_redirects=False)
        assert page.status_code == 403
        assert "Belum ada akun" in page.text
