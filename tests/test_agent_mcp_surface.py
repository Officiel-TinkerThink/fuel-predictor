"""End-to-end coverage of the read-only MCP surface (Phase 4, ADR 0008).

Driven through the real app: a credential is issued on the admin page exactly
as an operator would, then used as a bearer token against `/mcp`. Testing the
seam any lower would not prove the two halves agree about the token.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app

_ADMIN = ("admin", "kata-sandi-admin-1")

_HEADERS = (
    "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
)
_HISTORY = _HEADERS + "\n".join(
    [
        "ANGBER,transport,,20,18,manual",
        "ANGBER,transport,,40,28,manual",
        "ANGBER,lifting,2,20,25,routing_provider",
        "ANGBER,transport_and_lifting,3,45,42,routing_provider",
    ]
)


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


def _issue(client: TestClient, name: str, scopes: list[str]) -> str:
    page = client.get("/integrasi-agen")
    response = client.post(
        "/integrasi-agen",
        data={"name": name, "csrf_token": _csrf_token(page.text), "scopes": scopes},
    )
    assert response.status_code == 201, response.text
    return _issued_token(response.text)


def _issued_token(html: str) -> str:
    start = html.index("<code>") + len("<code>")
    return html[start : html.index("</code>", start)]


def _rpc(
    client: TestClient, token: str | None, method: str, params: Any = None, request_id: int = 1
) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/mcp", json=body, headers=headers)


def _tool_names(response: Any) -> set[str]:
    return {tool["name"] for tool in response.json()["result"]["tools"]}


def _activate_a_model(client: TestClient) -> None:
    # A signed-in operator's multipart upload carries CSRF like any other form.
    upload = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", _HISTORY.encode(), "text/csv")},
        data={"csrf_token": _csrf_token(client.get("/integrasi-agen").text)},
    )
    assert upload.status_code == 201, upload.text
    dataset = upload.json()["dataset_version"]
    candidate = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    ).json()
    promoted = client.post(f"/api/v1/model-candidates/{candidate['model_version_id']}/promote")
    assert promoted.status_code == 200, promoted.text


def test_mcp_refuses_calls_that_carry_no_credential(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        response = _rpc(client, None, "tools/list")

    assert response.status_code == 401
    # A compliant client needs to learn it must authenticate, not guess that
    # the server is broken.
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="fuel-predictor"'


def test_a_nonsense_token_is_refused_the_same_way_a_revoked_one_is(tmp_path: Path) -> None:
    """Probing must not be able to tell 'never existed' from 'was revoked'."""
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        page = client.get("/integrasi-agen")
        client_id = page.text.split('action="/integrasi-agen/')[1].split("/cabut")[0]
        client.post(
            f"/integrasi-agen/{client_id}/cabut",
            data={"csrf_token": _csrf_token(page.text)},
        )
        revoked = _rpc(client, token, "tools/list")
        nonsense = _rpc(client, "fpa_bukan-token-sungguhan", "tools/list")

    assert revoked.status_code == nonsense.status_code == 401
    assert revoked.json()["error"] == nonsense.json()["error"]


def test_initialize_announces_the_protocol_and_the_server(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        response = _rpc(client, token, "initialize")

    result = response.json()["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "fuel-predictor"
    assert result["capabilities"]["tools"] == {}


def test_tools_list_hides_tools_the_credential_could_not_call(tmp_path: Path) -> None:
    """Advertising an uncallable tool invites an agent to plan around it, then fail."""
    with _signed_in(tmp_path) as client:
        narrow = _issue(client, "Agen Model", ["models:read"])
        broad = _issue(client, "Agen Penuh", ["fuel:predict", "fuel:monitor", "models:read"])
        narrow_tools = _tool_names(_rpc(client, narrow, "tools/list"))
        broad_tools = _tool_names(_rpc(client, broad, "tools/list"))

    assert narrow_tools == {"get_current_model", "list_model_versions"}
    assert "predict_fuel" in broad_tools
    assert "get_drift_summary" in broad_tools
    assert narrow_tools < broad_tools


def test_calling_an_out_of_scope_tool_is_denied_and_recorded(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Model", ["models:read"])
        response = _rpc(
            client, token, "tools/call", {"name": "predict_fuel", "arguments": {}}
        )
        audit = client.get("/api/v1/audit-records").json()

    assert response.json()["error"]["code"] == -32003
    denied = [
        record
        for record in audit["records"]
        if record["action"] == "mcp_tool:predict_fuel" and record["outcome"] == "denied"
    ]
    # The denial has to leave a trace naming the agent, or revoking the right
    # credential after the fact becomes guesswork.
    assert len(denied) == 1
    assert denied[0]["actor"] == "Agen Model"


def test_an_unknown_tool_name_is_a_method_not_found(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        response = _rpc(
            client, token, "tools/call", {"name": "hapus_semua", "arguments": {}}
        )

    assert response.json()["error"]["code"] == -32601


def test_a_failing_tool_reports_a_tool_error_rather_than_a_broken_transport(
    tmp_path: Path,
) -> None:
    """The call reached the tool; the agent needs to see why it failed."""
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        response = _rpc(
            client,
            token,
            "tools/call",
            # lifting_hours is required by this mode, so the domain rejects it.
            {
                "name": "predict_fuel",
                "arguments": {
                    "vehicle_category": "ANGBER",
                    "activity_mode": "lifting",
                    "total_distance_km": 20,
                },
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert "error" not in body
    assert body["result"]["isError"] is True
    # Named explicitly so this cannot start passing for a different reason,
    # such as there being no active model to predict with.
    assert "lifting" in body["result"]["content"][0]["text"].lower()


def test_a_lookup_failure_inside_a_tool_is_not_reported_as_a_missing_tool(
    tmp_path: Path,
) -> None:
    """Regression: `KeyError` is a `LookupError`.

    Catching `LookupError` to mean "unknown tool" made a prediction attempted
    with no trained model come back as JSON-RPC -32601 with an empty message,
    telling the agent the tool does not exist rather than why the call failed.
    """
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        response = _rpc(
            client,
            token,
            "tools/call",
            {
                "name": "predict_fuel",
                "arguments": {
                    "vehicle_category": "ANGBER",
                    "activity_mode": "transport",
                    "total_distance_km": 20,
                },
            },
        )

    body = response.json()
    assert "error" not in body, body
    text = body["result"]["content"][0]["text"]
    assert body["result"]["isError"] is True
    assert "baseline" in text.lower()


def test_predict_fuel_returns_a_real_prediction_with_its_safety_framing(
    tmp_path: Path,
) -> None:
    import json

    with _signed_in(tmp_path) as client:
        _activate_a_model(client)
        token = _issue(client, "Agen Prediksi", ["fuel:predict"])
        response = _rpc(
            client,
            token,
            "tools/call",
            {
                "name": "predict_fuel",
                "arguments": {
                    "vehicle_category": "ANGBER",
                    "activity_mode": "transport_and_lifting",
                    "lifting_hours": 2,
                    "total_distance_km": 35,
                },
            },
        )
        audit = client.get("/api/v1/audit-records").json()

    result = response.json()["result"]
    assert result.get("isError") is not True, result
    payload = json.loads(result["content"][0]["text"])
    assert payload["estimated_fuel_requirement_liters"] > 0
    assert payload["recommended_allocation_liters"] > 0
    assert payload["model_version_id"].startswith("MDL-")
    # An agent must be able to tell prepared fuel from verified consumption.
    assert payload["safety_policy"]
    assert any(
        record["action"] == "mcp_tool:predict_fuel" and record["outcome"] == "succeeded"
        for record in audit["records"]
    )


def test_the_issued_token_is_shown_once_and_never_again(tmp_path: Path) -> None:
    """Only the hash is stored, so a lost credential is reissued, not looked up."""
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Uji", ["fuel:predict"])
        later = client.get("/integrasi-agen")

    assert token.startswith("fpa_")
    assert token not in later.text


def test_a_credential_with_no_scopes_is_refused(tmp_path: Path) -> None:
    with _signed_in(tmp_path) as client:
        page = client.get("/integrasi-agen")
        response = client.post(
            "/integrasi-agen",
            data={"name": "Agen Kosong", "csrf_token": _csrf_token(page.text)},
        )

    assert response.status_code == 422
    assert "cakupan" in response.text.lower()
