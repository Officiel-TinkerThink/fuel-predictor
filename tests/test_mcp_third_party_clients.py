"""What a coding agent's MCP client does that our own tests never did.

Claude Code, Cursor, Codex and VS Code all speak Streamable HTTP through the
official SDKs. Before the first tool call they probe: a GET to open a
notification stream, a `ping`, notifications other than `initialized`, and
on shutdown a DELETE. Each has a prescribed answer; a framework default in
its place makes the client report a broken server. These tests are the
contract for exposing `/mcp` to someone else's agent.
"""

import html
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")
# What the TypeScript SDK sends on every request once the handshake is done.
_SDK_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def _signed_in(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    )
    client.__enter__()
    client.post(
        "/masuk",
        data={
            "username": _ADMIN[0],
            "password": _ADMIN[1],
            "csrf_token": _csrf_token(client.get("/masuk").text),
        },
        follow_redirects=False,
    )
    return client


def _csrf_token(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _issue(client: TestClient, name: str = "Agen Pihak Ketiga") -> tuple[str, str]:
    page = client.get("/integrasi-agen")
    response = client.post(
        "/integrasi-agen",
        data={"name": name, "csrf_token": _csrf_token(page.text), "scopes": ["fuel:predict"]},
    )
    assert response.status_code == 201, response.text
    start = response.text.index("<code>") + len("<code>")
    # Unescaped: the snippets are read by a person, and the assertions below
    # compare them with what that person would paste.
    return response.text[start : response.text.index("</code>", start)], html.unescape(
        response.text
    )


def _rpc(client: TestClient, token: str, body: dict[str, Any]) -> Any:
    return client.post(
        "/mcp",
        json=body,
        headers={"Authorization": f"Bearer {token}", **_SDK_HEADERS},
    )


def test_a_get_is_answered_405_so_the_client_knows_there_is_no_stream(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token, _ = _issue(client)
        response = client.get("/mcp", headers={"Authorization": f"Bearer {token}", **_SDK_HEADERS})

    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"


def test_a_delete_is_answered_405_because_no_session_was_ever_issued(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token, _ = _issue(client)
        response = client.delete("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 405


def test_the_sdk_handshake_ping_and_notifications_are_all_answered(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token, _ = _issue(client)
        initialized = _rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-code", "version": "2.0.0"},
                },
            },
        )
        heard = _rpc(client, token, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        cancelled = _rpc(
            client,
            token,
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}},
        )
        pong = _rpc(client, token, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        listed = _rpc(client, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    # Answered with the revision this server implements; the SDK downgrades.
    assert initialized.json()["result"]["protocolVersion"] == "2024-11-05"
    assert initialized.headers["content-type"].startswith("application/json")
    assert initialized.headers["cache-control"] == "no-store"
    assert heard.status_code == 202 and heard.content == b""
    assert cancelled.status_code == 202
    assert pong.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert "predict_fuel" in {t["name"] for t in listed.json()["result"]["tools"]}


def test_a_credential_arrives_with_paste_ready_connection_snippets(tmp_path: Path) -> None:
    """The person connecting is rarely the person who issued the credential."""
    with _signed_in(tmp_path) as client:
        token, page = _issue(client, "Agen Kontraktor")

    assert "Cara menghubungkan" in page
    assert "http://testserver/mcp" in page
    command = (
        "claude mcp add --transport http fuel-predictor http://testserver/mcp "
        f'--header "Authorization: Bearer {token}"'
    )
    assert command in page
    mcp_json_start = page.index('"mcpServers"')
    assert token in page[mcp_json_start:]
    assert "[mcp_servers.fuel-predictor]" in page
    assert "tools/list" in page
    # The token is the same in every snippet; a page that rendered a stale
    # or different one would send the reader to a 401 with no explanation.
    assert page.count(token) >= 5


def test_the_snippets_are_not_shown_until_a_credential_is_issued(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        page = client.get("/integrasi-agen").text

    assert "Cara menghubungkan" not in page


def test_the_curl_snippet_is_a_working_call(tmp_path: Path) -> None:
    """Render the snippet, then make the exact request it describes."""
    with _signed_in(tmp_path) as client:
        token, page = _issue(client)
        start = page.index("curl -sS")
        snippet = page[start : page.index("</pre>", start)]
        body = json.loads(snippet[snippet.index("-d '") + 4 : snippet.rindex("'")])
        response = client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})

    assert body == {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert "predict_fuel" in {t["name"] for t in response.json()["result"]["tools"]}
