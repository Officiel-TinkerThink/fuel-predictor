"""Managing MCP client credentials (Phase 4, ADR 0008)."""

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, Response

from fuel_predictor.application.agent_credentials import (
    IssueAgentCredential,
    ListAgentClients,
    RevokeAgentCredential,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import AgentScope, IdentityValidationError

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller


def build_agent_pages_router(
    issue_credential: IssueAgentCredential,
    revoke_credential: RevokeAgentCredential,
    list_clients: ListAgentClients,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/integrasi-agen", response_class=HTMLResponse)
    def show_agents(request: Request) -> HTMLResponse:
        return HTMLResponse(_render(guard.require_caller(request), list_clients, None, None))

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
                _render(caller, list_clients, None, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        # Shown exactly once. Only the hash is stored, so this value cannot be
        # recovered later — a lost credential is reissued, not looked up.
        return HTMLResponse(
            _render(caller, list_clients, issued.token, None),
            status_code=status.HTTP_201_CREATED,
        )

    @router.post("/integrasi-agen/{client_id}/cabut", response_class=HTMLResponse)
    async def revoke(client_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            revoke_credential.execute(client_id, revoked_by=caller.user.username)
        except IdentityValidationError as error:
            return HTMLResponse(
                _render(caller, list_clients, None, error.message),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(_render(caller, list_clients, None, None))

    return router


def _render(
    caller: "ActiveCaller",
    list_clients: ListAgentClients,
    issued_token: str | None,
    error: str | None,
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
    )
