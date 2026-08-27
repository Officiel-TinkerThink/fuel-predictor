"""Verify `/mcp` against the official MCP SDK client.

    python scripts/verify-mcp-client.py http://127.0.0.1:8000/mcp fpa_...

The acceptance criterion is that prediction and monitoring work "through a
standards-compliant remote client". Hand-rolled JSON-RPC cannot show that: it
only proves our client and our server agree with each other, which they would
even if both were wrong. This drives the real `mcp` SDK instead.

Kept as a script rather than a test because it needs a *running* server — the
SDK speaks real HTTP, not ASGI-in-process — and a test that spawns uvicorn
would be slow and flaky. Run it against a deployment after any change to the
MCP surface, and as part of the handoff drill.

`mcp` is not a declared dependency; it arrives transitively with mlflow. If
this ever fails to import, install it rather than assuming the server changed.
"""

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

_READ_ONLY = (
    "get_service_health",
    "get_drift_summary",
    "get_performance_summary",
    "get_current_model",
    "list_model_versions",
    "get_prediction_input_schema",
)
_PREDICT = {
    "vehicle_category": "ANGBER",
    "activity_mode": "transport_and_lifting",
    "lifting_hours": 2,
    "total_distance_km": 35,
}


def _report(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
    return ok


async def verify(url: str, token: str) -> int:
    failures = 0
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
        read,
        write,
        _,
    ), ClientSession(read, write) as session:
        info = await session.initialize()
        failures += not _report(
            "initialize", info.serverInfo.name == "fuel-predictor", info.serverInfo.name
        )

        listed = {tool.name for tool in (await session.list_tools()).tools}
        failures += not _report("tools/list", bool(listed), f"{len(listed)} tools")

        if "predict_fuel" in listed:
            result = await session.call_tool("predict_fuel", _PREDICT)
            payload = json.loads(result.content[0].text) if not result.isError else {}
            failures += not _report(
                "predict_fuel",
                not result.isError
                and payload.get("estimated_fuel_requirement_liters", 0) > 0
                and bool(payload.get("safety_policy")),
                result.content[0].text[:70],
            )

        for name in _READ_ONLY:
            if name not in listed:
                continue
            result = await session.call_tool(name, {})
            failures += not _report(name, not result.isError)

        # A privileged preview must change nothing. Skipped when the tools
        # are disabled, which is the expected production default.
        if "activate_model_version" in listed:
            current = json.loads(
                (await session.call_tool("get_current_model", {})).content[0].text
            )
            preview = json.loads(
                (
                    await session.call_tool(
                        "activate_model_version",
                        {"model_version_id": current["model_version_id"]},
                    )
                ).content[0].text
            )
            after = json.loads(
                (await session.call_tool("get_current_model", {})).content[0].text
            )
            failures += not _report(
                "privileged preview changes nothing",
                preview.get("status") == "confirmation_required"
                and after["model_version_id"] == current["model_version_id"],
            )
        else:
            print("  SKIP  privileged tools (disabled, which is the production default)")

        try:
            await session.call_tool("tidak_ada_alat_ini", {})
            failures += not _report("unknown tool rejected", False, "no error raised")
        except McpError:
            failures += not _report("unknown tool rejected", True)

    print(f"\n{'PASS' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(verify(sys.argv[1], sys.argv[2])))
