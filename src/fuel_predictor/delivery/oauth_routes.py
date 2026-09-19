"""The OAuth 2.1 authorization server an MCP client talks to (ADR 0014).

Discovery documents, dynamic registration, the authorization endpoint with
its consent page, the token endpoint and revocation. Every response shape
here is dictated by a specification a third-party client was written
against, so the field names are theirs, not ours; the messages inside them
are in Indonesian like the rest of the application because a person may
end up reading them on a consent or error page.

Where a request fails is what decides how it is answered. A fault in the
client or its redirect address is shown to the user on this site, because
sending them elsewhere is exactly what a hostile request wants. Any other
fault goes back to the registered redirect as the specification requires.
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from fuel_predictor.application.agent_grants import (
    IssueAuthorizationCode,
    IssuedGrantTokens,
    RedeemAuthorizationCode,
    RedirectableAuthorizationError,
    RefreshGrant,
    RegisterAgentClient,
    RevokeGrantByToken,
    ValidateAuthorizationRequest,
)
from fuel_predictor.delivery.rendering import render, render_error_page
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.agent_authorization import AgentAuthorizationError
from fuel_predictor.domain.identity import AgentScope

# What a scope means, in words a planner deciding whether to allow it can weigh.
SCOPE_DESCRIPTIONS: dict[AgentScope, str] = {
    AgentScope.PREDICT: "Membuat prediksi BBM, mencari operasi serupa, dan memeriksa rute",
    AgentScope.MONITOR: "Melihat kesehatan sistem, pergeseran data, dan kinerja model",
    AgentScope.MODELS_READ: "Melihat model aktif dan riwayat versinya",
    AgentScope.MODELS_ADMIN: "Mengaktifkan dan mengembalikan model (cakupan istimewa)",
}

_SCOPE_VALUES = frozenset(str(scope) for scope in AgentScope)
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def build_oauth_router(
    *,
    register_client: RegisterAgentClient,
    validate_request: ValidateAuthorizationRequest,
    issue_code: IssueAuthorizationCode,
    redeem_code: RedeemAuthorizationCode,
    refresh_grant: RefreshGrant,
    revoke_by_token: RevokeGrantByToken,
    guard: SecurityGuard,
    is_system_provisioned: Callable[[], bool],
    public_url: str | None = None,
) -> APIRouter:
    router = APIRouter()

    def base_url(request: Request) -> str:
        return public_origin(request, public_url)

    # --- Discovery (RFC 9728, RFC 8414) --------------------------------------

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource(request: Request) -> JSONResponse:
        """Where `/mcp` says its tokens come from. Both paths: clients derive
        either the origin-wide or the path-suffixed form from the MCP URL."""
        base = base_url(request)
        return JSONResponse(
            {
                "resource": f"{base}/mcp",
                "authorization_servers": [base],
                "scopes_supported": [str(scope) for scope in AgentScope],
                "bearer_methods_supported": ["header"],
            },
            headers=_NO_STORE,
        )

    @router.get("/.well-known/oauth-authorization-server")
    @router.get("/.well-known/openid-configuration")
    async def authorization_server(request: Request) -> JSONResponse:
        """The endpoints below, by name. The OpenID path is the fallback some
        clients try second; the same document satisfies them."""
        base = base_url(request)
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "registration_endpoint": f"{base}/oauth/register",
                "revocation_endpoint": f"{base}/oauth/revoke",
                "response_types_supported": ["code"],
                "response_modes_supported": ["query"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": [str(scope) for scope in AgentScope],
            },
            headers=_NO_STORE,
        )

    # --- Dynamic client registration (RFC 7591) --------------------------------

    @router.post("/oauth/register")
    async def register(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - malformed body is the client's error
            return _oauth_error("invalid_client_metadata", "Isi permintaan harus JSON.")
        if not isinstance(payload, dict):
            return _oauth_error("invalid_client_metadata", "Isi permintaan harus objek JSON.")
        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not all(
            isinstance(uri, str) for uri in redirect_uris
        ):
            return _oauth_error("invalid_redirect_uri", "redirect_uris harus berupa daftar string.")
        # A client may ask for a secret or another grant type; it does not
        # get one. Saying so in the response is the specification's way of
        # letting it decide whether it can live with that.
        client_name = payload.get("client_name")
        try:
            registration = register_client.execute(
                client_name=client_name if isinstance(client_name, str) else None,
                redirect_uris=redirect_uris,
            )
        except AgentAuthorizationError as error:
            return _oauth_error(error.error, error.description)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "client_id": registration.registration_id,
                "client_id_issued_at": int(registration.registered_at.timestamp()),
                "client_name": registration.client_name,
                "redirect_uris": sorted(registration.redirect_uris),
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
            headers=_NO_STORE,
        )

    # --- Authorization endpoint and consent -----------------------------------------

    @router.get("/oauth/authorize", response_class=HTMLResponse)
    async def show_consent(request: Request) -> Response:
        caller = guard.require_caller(request)
        if not is_system_provisioned():
            return _consent_unavailable()
        query = request.query_params
        try:
            authorization = validate_request.execute(
                client_id=query.get("client_id"),
                redirect_uri=query.get("redirect_uri"),
                response_type=query.get("response_type"),
                code_challenge=query.get("code_challenge"),
                code_challenge_method=query.get("code_challenge_method"),
                scope=query.get("scope"),
                state=query.get("state"),
                resource=query.get("resource"),
                expected_resource=f"{base_url(request)}/mcp",
            )
        except RedirectableAuthorizationError as error:
            return _redirect_with_error(error)
        except AgentAuthorizationError as error:
            return _consent_refused(error)

        offered = authorization.offered_scopes_for(caller.user)
        refused = authorization.requested_scopes - offered
        return HTMLResponse(
            render(
                "oauth-izin.html",
                caller=caller,
                page_title="Izinkan agen mengakses atas nama Anda?",
                eyebrow="AGEN",
                client_name=authorization.registration.client_name,
                redirect_host=authorization.redirect_host,
                offered_scopes=[
                    {"value": str(scope), "description": SCOPE_DESCRIPTIONS[scope]}
                    for scope in sorted(offered)
                ],
                refused_scopes=[str(scope) for scope in sorted(refused)],
                # Echoed back so the POST can re-validate everything from
                # scratch; nothing about the request is trusted from the GET.
                hidden_fields={
                    key: value
                    for key, value in query.items()
                    if key
                    in {
                        "client_id",
                        "redirect_uri",
                        "response_type",
                        "code_challenge",
                        "code_challenge_method",
                        "scope",
                        "state",
                        "resource",
                    }
                },
            )
        )

    @router.post("/oauth/authorize")
    async def decide(request: Request) -> Response:
        caller = guard.require_caller(request)
        if not is_system_provisioned():
            return _consent_unavailable()
        form = await request.form()

        def field(name: str) -> str | None:
            value = form.get(name)
            return value if isinstance(value, str) and value != "" else None

        try:
            authorization = validate_request.execute(
                client_id=field("client_id"),
                redirect_uri=field("redirect_uri"),
                response_type=field("response_type"),
                code_challenge=field("code_challenge"),
                code_challenge_method=field("code_challenge_method"),
                scope=field("scope"),
                state=field("state"),
                resource=field("resource"),
                expected_resource=f"{base_url(request)}/mcp",
            )
        except RedirectableAuthorizationError as error:
            return _redirect_with_error(error)
        except AgentAuthorizationError as error:
            return _consent_refused(error)

        if field("decision") != "izinkan":
            return _redirect_with_error(
                RedirectableAuthorizationError(
                    "access_denied",
                    "Pengguna menolak permintaan.",
                    redirect_uri=authorization.redirect_uri,
                    state=authorization.state,
                )
            )

        consented = frozenset(
            AgentScope(value)
            for value in form.getlist("scopes")
            if isinstance(value, str) and value in _SCOPE_VALUES
        )
        try:
            issued = issue_code.execute(authorization, caller.user, consented)
        except RedirectableAuthorizationError as error:
            return _redirect_with_error(error)

        parameters = {"code": issued.code}
        if issued.state is not None:
            parameters["state"] = issued.state
        return RedirectResponse(
            _with_query(issued.redirect_uri, parameters),
            status_code=status.HTTP_303_SEE_OTHER,
            headers=_NO_STORE,
        )

    # --- Token endpoint and revocation (RFC 6749 §3.2, RFC 7009) -----------------------

    @router.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()

        def field(name: str) -> str | None:
            value = form.get(name)
            return value if isinstance(value, str) else None

        grant_type = field("grant_type")
        try:
            if grant_type == "authorization_code":
                issued = redeem_code.execute(
                    code=field("code"),
                    client_id=field("client_id"),
                    redirect_uri=field("redirect_uri"),
                    code_verifier=field("code_verifier"),
                    resource=field("resource"),
                    expected_resource=f"{base_url(request)}/mcp",
                )
            elif grant_type == "refresh_token":
                issued = refresh_grant.execute(
                    refresh_token=field("refresh_token"),
                    client_id=field("client_id"),
                    scope=field("scope"),
                )
            else:
                return _oauth_error(
                    "unsupported_grant_type",
                    "grant_type harus authorization_code atau refresh_token.",
                )
        except AgentAuthorizationError as error:
            return _oauth_error(error.error, error.description)
        return JSONResponse(_token_body(issued), headers=_NO_STORE)

    @router.post("/oauth/revoke")
    async def revoke(request: Request) -> Response:
        form = await request.form()
        token_value = form.get("token")
        client_id = form.get("client_id")
        revoke_by_token.execute(
            token=token_value if isinstance(token_value, str) else None,
            client_id=client_id if isinstance(client_id, str) else None,
        )
        return Response(status_code=status.HTTP_200_OK, headers=_NO_STORE)

    return router


def public_origin(request: Request, configured: str | None) -> str:
    """This server as the client reaches it.

    The configured public URL when there is one: an OAuth issuer has to be
    stable and exactly what the client sees, and behind a CDN or a gateway
    that does not forward the original scheme the request alone cannot say.
    Otherwise the request's own origin: the public https one when every
    proxy forwards it (uvicorn --proxy-headers), the plain local one in
    development."""
    return configured or str(request.base_url).rstrip("/")


def _token_body(issued: IssuedGrantTokens) -> dict[str, Any]:
    return {
        "access_token": issued.access_token,
        "token_type": "Bearer",
        "expires_in": issued.expires_in,
        "refresh_token": issued.refresh_token,
        "scope": " ".join(sorted(str(scope) for scope in issued.scopes)),
    }


def _oauth_error(error: str, description: str) -> JSONResponse:
    # RFC 6749 §5.2: 400 for everything except a client that failed to
    # authenticate, which is 401 so the client knows to re-register.
    http_status = (
        status.HTTP_401_UNAUTHORIZED if error == "invalid_client" else status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse(
        status_code=http_status,
        content={"error": error, "error_description": description},
        headers=_NO_STORE,
    )


def _redirect_with_error(error: RedirectableAuthorizationError) -> RedirectResponse:
    parameters = {"error": error.error, "error_description": error.description}
    if error.state is not None:
        parameters["state"] = error.state
    return RedirectResponse(
        _with_query(error.redirect_uri, parameters),
        status_code=status.HTTP_303_SEE_OTHER,
        headers=_NO_STORE,
    )


def _with_query(url: str, parameters: dict[str, str]) -> str:
    """Append to whatever query the registered redirect already carries."""
    parts = urlsplit(url)
    query = f"{parts.query}&{urlencode(parameters)}" if parts.query else urlencode(parameters)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _consent_refused(error: AgentAuthorizationError) -> HTMLResponse:
    """Shown here, on purpose: the client or its redirect is what is wrong."""
    return HTMLResponse(
        render_error_page(
            "Permintaan agen tidak dapat diproses",
            f"{error.description} (kode: {error.error}). Periksa konfigurasi agen yang "
            "meminta akses, lalu coba sambungkan lagi.",
        ),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _consent_unavailable() -> HTMLResponse:
    return HTMLResponse(
        render_error_page(
            "Belum ada akun",
            "Persetujuan agen memerlukan akun pengguna. Buat administrator pertama lebih "
            "dahulu, lalu sambungkan agen dari akun tersebut.",
        ),
        status_code=status.HTTP_403_FORBIDDEN,
    )
