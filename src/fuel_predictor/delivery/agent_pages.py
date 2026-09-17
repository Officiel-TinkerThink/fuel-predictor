"""Managing MCP client credentials (ADR 0008) and user-connected agents (ADR 0014).

Two pages. *Integrasi Agen* is the administrator's: static credentials are
issued and revoked there, and every user's OAuth grant is listed with a
revoke action. *Agen Saya* is everyone's: their own grants, and how to
connect a new agent without a credential at all.
"""

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, Response

from fuel_predictor.application.agent_credentials import (
    IssueAgentCredential,
    ListAgentClients,
    RevokeAgentCredential,
)
from fuel_predictor.application.agent_grants import (
    AgentGrantSummary,
    ListAgentGrants,
    RevokeAgentGrant,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import (
    DEFAULT_AGENT_SCOPES,
    AgentScope,
    IdentityValidationError,
)

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller


def build_agent_pages_router(
    issue_credential: IssueAgentCredential,
    revoke_credential: RevokeAgentCredential,
    list_clients: ListAgentClients,
    guard: SecurityGuard,
    rate_limit_per_minute: int = 0,
    *,
    list_grants: ListAgentGrants,
    revoke_grant: RevokeAgentGrant,
) -> APIRouter:
    router = APIRouter()

    def _admin_page(
        caller: "ActiveCaller",
        issued_token: str | None = None,
        error: str | None = None,
        connection: dict[str, object] | None = None,
    ) -> str:
        return _render(
            caller,
            list_clients,
            issued_token,
            error,
            connection=connection,
            grants=list_grants.execute(),
        )

    @router.get("/integrasi-agen", response_class=HTMLResponse)
    def show_agents(request: Request) -> HTMLResponse:
        return HTMLResponse(_admin_page(guard.require_caller(request)))

    @router.post("/integrasi-agen", response_class=HTMLResponse)
    async def issue(request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        scopes = frozenset(
            AgentScope(value) for value in form.getlist("scopes") if isinstance(value, str)
        )
        try:
            issued = issue_credential.execute(
                name=str(form.get("name", "")), scopes=scopes, issued_by=caller.user.username
            )
        except IdentityValidationError as error:
            return HTMLResponse(
                _admin_page(caller, error=error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        # Shown exactly once. Only the hash is stored, so this value cannot be
        # recovered later — a lost credential is reissued, not looked up.
        return HTMLResponse(
            _admin_page(
                caller,
                issued_token=issued.token,
                connection=_connection_guide(
                    _mcp_url(request), issued.token, rate_limit_per_minute
                ),
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.post("/integrasi-agen/{client_id}/cabut", response_class=HTMLResponse)
    async def revoke(client_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            revoke_credential.execute(client_id, revoked_by=caller.user.username)
        except IdentityValidationError as error:
            return HTMLResponse(
                _admin_page(caller, error=error.message),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(_admin_page(caller))

    @router.post("/integrasi-agen/grant/{grant_id}/cabut", response_class=HTMLResponse)
    async def revoke_any_grant(grant_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            revoke_grant.execute(grant_id, revoked_by=caller.user)
        except IdentityValidationError as error:
            return HTMLResponse(
                _admin_page(caller, error=error.message),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(_admin_page(caller))

    # --- Agen Saya: a user's own grants -------------------------------------

    def _own_page(request: Request, caller: "ActiveCaller", error: str | None = None) -> str:
        url = _mcp_url(request)
        return render(
            "agen-saya.html",
            caller=caller,
            page_title="Agen Saya",
            active_path="/agen-saya",
            eyebrow="PENGATURAN",
            page_lead=(
                "Agen pengkodean yang Anda sambungkan bertindak atas nama akun Anda. "
                "Cabut sambungannya di sini bila tidak dipakai lagi."
            ),
            grants=list_grants.execute(user_id=caller.user.user_id),
            error=error,
            mcp_url=url,
            mcp_json=json.dumps(
                {"mcpServers": {"fuel-predictor": {"type": "http", "url": url}}}, indent=2
            ),
        )

    @router.get("/agen-saya", response_class=HTMLResponse)
    def show_own_agents(request: Request) -> HTMLResponse:
        return HTMLResponse(_own_page(request, guard.require_caller(request)))

    @router.post("/agen-saya/{grant_id}/cabut", response_class=HTMLResponse)
    async def revoke_own_grant(grant_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            revoke_grant.execute(grant_id, revoked_by=caller.user)
        except IdentityValidationError as error:
            return HTMLResponse(
                _own_page(request, caller, error.message), status_code=status.HTTP_404_NOT_FOUND
            )
        return HTMLResponse(_own_page(request, caller))

    return router


def _mcp_url(request: Request) -> str:
    """The address as the outside world reaches it.

    Behind the gateway uvicorn rewrites the scheme and host from the forwarded
    headers (--proxy-headers), so this is the public https URL in production
    and the plain local one in development.
    """
    return str(request.url.replace(path="/mcp", query="", fragment=""))


def _connection_guide(url: str, token: str, rate_limit: int) -> dict[str, object]:
    """Ready-to-paste configuration for the agents people actually use.

    Generated with the credential filled in, because the person receiving
    it is typically not the person who issued it: a snippet they can paste
    unchanged removes the one step where a token gets mistyped.
    """
    header = f"Authorization: Bearer {token}"
    mcp_json = json.dumps(
        {
            "mcpServers": {
                "fuel-predictor": {
                    "type": "http",
                    "url": url,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        },
        indent=2,
    )
    codex = (
        "[mcp_servers.fuel-predictor]\n"
        f'url = "{url}"\n'
        f'http_headers = {{ "Authorization" = "Bearer {token}" }}'
    )
    claude_code = f'claude mcp add --transport http fuel-predictor {url} --header "{header}"'
    curl = (
        f"curl -sS {url} -H 'Content-Type: application/json' -H '{header}' "
        '-d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\''
    )
    return {
        "mcp_url": url,
        "rate_limit": rate_limit,
        "snippets": {
            "claude_code": claude_code,
            "mcp_json": mcp_json,
            "codex": codex,
            "curl": curl,
        },
    }


def _render(
    caller: "ActiveCaller",
    list_clients: ListAgentClients,
    issued_token: str | None,
    error: str | None,
    connection: dict[str, object] | None = None,
    grants: tuple[AgentGrantSummary, ...] = (),
) -> str:
    return render(
        "integrasi-agen.html",
        caller=caller,
        page_title="Integrasi Agen",
        active_path="/integrasi-agen",
        eyebrow="PENGATURAN",
        page_lead=(
            "Setiap klien agen memiliki kredensial dan cakupan sendiri, sehingga satu klien "
            "dapat dicabut tanpa mengganggu yang lain."
        ),
        clients=list_clients.execute(),
        issued_token=issued_token,
        error=error,
        available_scopes=[str(scope) for scope in AgentScope],
        # Only the read/compute scopes are pre-checked. A privileged scope must
        # be a deliberate tick, not something a credential inherits from an
        # administrator accepting the form as presented.
        default_scopes=[str(scope) for scope in DEFAULT_AGENT_SCOPES],
        mcp_url=connection["mcp_url"] if connection else None,
        rate_limit=connection["rate_limit"] if connection else None,
        snippets=connection["snippets"] if connection else None,
        grants=grants,
    )
