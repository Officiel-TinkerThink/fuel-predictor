# Connecting an agent to the fuel-predictor MCP server

For the developer (or the coding agent) on the other side: what the endpoint is, how to
authenticate, what the tools do, and what to expect when something goes wrong. Hand this file
over together with a credential issued from **Integrasi Agen**.

---

## 1. Endpoint

| | |
|---|---|
| URL | `https://<domain>/mcp` (the same host as the web application) |
| Transport | MCP **Streamable HTTP**, stateless: one `POST` per JSON-RPC message, one JSON body back. No SSE stream (`GET /mcp` → 405), no sessions (`DELETE /mcp` → 405). |
| Protocol revision | Server answers `initialize` with `2024-11-05`. Clients on `2025-03-26`, `2025-06-18`, `2025-11-25` downgrade automatically (verified with the official Python and TypeScript SDKs). |
| Authentication | `Authorization: Bearer fpa_…` on **every** request, `initialize` included. |
| Capabilities | `tools` only. No resources, prompts, sampling or OAuth. |
| Rate limit | Per credential, default 120 calls / 60 s. Exceeding it returns HTTP 429 with `Retry-After` and JSON-RPC error `-32004`. |

### Credentials

An administrator issues one per client on **Integrasi Agen** (shown once; only its hash is
stored) and can revoke it at any time, effective immediately. A revoked or unknown token gets the
same `401` with `WWW-Authenticate: Bearer realm="fuel-predictor"`. Scopes decide which tools are
listed and callable:

| Scope | Tools |
|---|---|
| `fuel:predict` | `predict_fuel`, `find_similar_operations`, `list_vehicles`, `search_locations`, `estimate_route_distance`, `get_prediction_input_schema` |
| `fuel:monitor` | `get_service_health`, `get_drift_summary`, `get_performance_summary` |
| `models:read` | `get_current_model`, `list_model_versions` |
| `models:admin` | privileged model activation — off by default, see ADR 0008/0010 |

`tools/list` only shows what the credential can call.

## 2. Client configuration

The page that issues the credential renders these with the token filled in. For reference:

**Claude Code**

```bash
claude mcp add --transport http fuel-predictor https://<domain>/mcp --header "Authorization: Bearer fpa_…"
```

**Cursor / Windsurf / VS Code** (`mcp.json` or `.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "fuel-predictor": {
      "type": "http",
      "url": "https://<domain>/mcp",
      "headers": { "Authorization": "Bearer fpa_…" }
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`)

```toml
[mcp_servers.fuel-predictor]
url = "https://<domain>/mcp"
http_headers = { "Authorization" = "Bearer fpa_…" }
```

**Python (official SDK)**

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
    async with ClientSession(r, w) as session:
        await session.initialize()
        result = await session.call_tool("predict_fuel", {...})
```

**Smoke test without any client**

```bash
curl -sS https://<domain>/mcp -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer fpa_…' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`scripts/verify-mcp-client.py <url> <token>` runs the full contract through the official SDK.

## 3. The recommendation flow

The tools are designed for this conversation: a planner says, in their own words, *"Buat
rekomendasi BBM untuk mobilisasi pipa menggunakan truck crane 01 dari pool limau ke SP II"*, and
the agent answers with the recommendation, its details, and similar past operations.

1. **Resolve names** (optional, but cheap): `list_vehicles` and `search_locations {"query": "sp ii"}`.
   Vehicle and stop names are matched case-, spacing-, hyphen- and numeral-insensitively
   (`"SP 2"` and `"sp ii"` both mean `SP-II`). If a name still does not resolve, the tool error
   lists the nearest candidates so the agent can ask the planner which one they meant.
2. **Route distance** (optional): `estimate_route_distance {"stop_sequence": [...]}`. Uses the
   routing provider when the deployment has one; otherwise a tool error asks for a manual distance.
3. **Recommend**: `predict_fuel`. This **creates a daily operation** and a prediction — it is a
   write, not a pure read, so call it once per planned operation, not speculatively.

```json
{
  "vehicle": "truck crane 01",
  "activity_mode": "transport",
  "stop_sequence": ["pool limau", "SP II", "pool limau"],
  "similar_limit": 5
}
```

`vehicle` and `activity_mode` are required. Give `stop_sequence` (planner's order, include the
return leg) so the distance comes from the route, or `total_distance_km` when the distance is
already known / the routing provider is unavailable. `lifting_hours` is required for
`lifting` and `transport_and_lifting`. Full schema: `get_prediction_input_schema`.

Result:

| field | meaning |
|---|---|
| `estimated_fuel_requirement_liters` | The model's estimate of **prepared** fuel — what to issue, not what will be burned. |
| `recommended_allocation_liters` | Conservative allocation (estimate + margin / upper bound). This is the number to give the planner. |
| `uncertainty_interval_liters` | `lower` / `upper`. |
| `safety_policy` | Sentence explaining the margin. **Relay it**: it says the estimate is not calibrated against actual consumption. |
| `details` | What the number was computed from, after resolution: canonical `vehicle` + `vehicle_group`, `activity_mode`, `lifting_hours`, `total_distance_km`, `distance_source` (`routing_provider` / `manual`), `route_distance_manual_fallback`, resolved `stop_sequence`, and the `model` (version, algorithm, feature version, training rows, uncertainty). |
| `similar_operations` | Past operations, ranked: same vehicle → same vehicle group → same category; then same activity mode; then nearest distance and lifting hours. Each row says where it came from (`source`: `dataset` = imported prepared-fuel history with `operation_date` and `source_reference`; `recorded` = an operation planned through the app/agent with `stop_sequence`, the estimate given then, and `actual_fuel_liters` once recorded), and a `match` block (`vehicle`: `same`/`same_group`/`same_category`, `activity_mode`, `distance_delta_km`, `lifting_hours_delta`, `score`). |
| `operation_id` | Quote it back to the planner: actual fuel is later recorded against it. |

`find_similar_operations` returns the same history without creating an operation.

## 4. Errors an agent should expect

| What comes back | Meaning | What to do |
|---|---|---|
| HTTP 401 | Missing, wrong or revoked credential | Ask the administrator for a new one. Do not retry. |
| JSON-RPC `-32003` | Tool needs a scope the credential lacks | Ask for the scope; `tools/list` already hides such tools. |
| HTTP 429 / `-32004` | Rate limit | Back off for `Retry-After` seconds. |
| `-32601` | Unknown tool or method | Re-read `tools/list`. |
| `isError: true` in a tool result | The call reached the tool and failed for a stated reason | Read the text. Unknown vehicle/stop → candidates are listed; missing `lifting_hours`; no active model (`baseline`); routing unavailable → supply `total_distance_km`. |

Every call is audited (client name, tool, outcome) on the **Catatan Audit** page.

## 5. What this is not

- Not OAuth. Clients that only support OAuth-discovered remote servers (claude.ai custom
  connectors, ChatGPT connectors) cannot use a static bearer token. Coding agents (Claude Code,
  Cursor, Codex, VS Code, Windsurf, Gemini CLI) can.
- Not a browser API. There is no CORS; use it from an agent or a server.
- Not actual consumption. Every number is an estimate of fuel to prepare (ADR 0002); the
  `actual_fuel_liters` in history rows is the only verified quantity.
