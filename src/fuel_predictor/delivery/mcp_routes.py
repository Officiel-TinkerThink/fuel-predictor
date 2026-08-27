"""HTTP surface for MCP at `/mcp` (Phase 4).

A minimal JSON-RPC endpoint implementing the handful of methods a read-only
client needs. The MCP SDK's own transport is deliberately not mounted yet:
its session/OAuth machinery is more surface than a three-tool read-only
launch requires, and the plan wants read-only operation proven before that
surface is widened. The request/response shapes here follow JSON-RPC 2.0 so
a standards-compliant client can talk to it.
"""

from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from fuel_predictor.delivery.mcp_server import (
    McpAuthenticationError,
    McpAuthorizationError,
    McpRateLimitError,
    McpRequestHandler,
    McpUnknownToolError,
    tool_result_to_text,
)

# The revision whose behaviour this server actually implements. Clients on a
# newer revision are answered with this one rather than echoed back: the spec
# has the server reply with a version it supports and lets the client decide
# whether to proceed, and claiming a newer revision we have not implemented
# would invite clients to expect features that are not here. Verified against
# the official SDK, which requests 2025-11-25 and downgrades cleanly.
_PROTOCOL_VERSION = "2024-11-05"


def build_mcp_router(handler: McpRequestHandler, server_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def handle(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - malformed body is a protocol error
            return _error(None, -32700, "Parse error")

        if not isinstance(payload, dict):
            return _error(None, -32600, "Invalid Request")

        request_id = payload.get("id")
        method = payload.get("method")

        try:
            client = handler.authenticate(request.headers.get("authorization"))
        except McpAuthenticationError as error:
            # 401 with WWW-Authenticate so a standards-compliant client knows
            # to obtain a credential rather than treating this as a bug.
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": 'Bearer realm="fuel-predictor"'},
                content=_body(request_id, error=(-32001, str(error))),
            )

        if method == "initialize":
            return _ok(
                request_id,
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fuel-predictor", "version": server_version},
                },
            )

        if method == "notifications/initialized":
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={})

        if method == "tools/list":
            return _ok(
                request_id,
                {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                        }
                        for tool in handler.registry.visible_to(client)
                    ]
                },
            )

        if method == "tools/call":
            params = payload.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str):
                return _error(request_id, -32602, "Invalid params: 'name' is required")
            try:
                result = handler.call(client, name, arguments)
            except McpAuthorizationError as error:
                return _error(request_id, -32003, str(error))
            except McpRateLimitError as error:
                # 429 as well as the JSON-RPC code: a proxy or client library
                # that understands nothing about MCP still knows to back off,
                # and Retry-After says for how long.
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": str(error.window_seconds)},
                    content=_body(request_id, error=(-32004, str(error))),
                )
            except McpUnknownToolError as error:
                return _error(request_id, -32601, str(error))
            except Exception as error:  # noqa: BLE001 - reported as a tool error
                # Returned as an MCP tool error rather than a transport error:
                # the call reached the tool, and the agent needs to see why it
                # failed rather than assuming the server is broken.
                return _ok(
                    request_id,
                    {
                        "content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}],
                        "isError": True,
                    },
                )
            return _ok(
                request_id,
                {"content": [{"type": "text", "text": tool_result_to_text(result)}]},
            )

        return _error(request_id, -32601, f"Method not found: {method}")

    return router


def _body(
    request_id: Any, *, result: Any = None, error: tuple[int, str] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        body["error"] = {"code": error[0], "message": error[1]}
    else:
        body["result"] = result
    return body


def _ok(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse(content=_body(request_id, result=result))


def _error(request_id: Any, code: int, message: str) -> JSONResponse:
    # JSON-RPC carries its own error codes, so the HTTP status stays 200 for
    # errors the protocol itself describes; only authentication uses 401.
    return JSONResponse(content=_body(request_id, error=(code, message)))
