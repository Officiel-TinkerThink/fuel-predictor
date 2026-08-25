"""Request-level authentication, CSRF, and capability checks (ADR 0008).

The middleware resolves the session once per request and stores the caller on
`request.state`. Routes then ask for a capability, never for a role, so the
authorization rule lives in the domain and the route only names what it needs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import compare_digest, token_urlsafe
from urllib.parse import quote

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fuel_predictor.application.identity import ActiveCaller, ResolveSession
from fuel_predictor.domain.identity import Capability, User, UserRole

SESSION_COOKIE = "fp_session"
CSRF_COOKIE = "fp_csrf"
CSRF_FIELD = "csrf_token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")

# Reachable without a session even once the system is provisioned.
_PUBLIC_PATHS = frozenset(
    {
        "/masuk",
        "/keluar",
        "/sehat",
        "/statis",
        "/docs",
        "/redoc",
        "/openapi.json",
        # /mcp carries its own bearer-token authentication and its own audit
        # trail (Phase 4). It is "public" only to the *session* middleware —
        # an unauthenticated MCP call is still rejected, by the MCP handler.
        "/mcp",
    }
)

# One entry per route: (method, path pattern, capability). A pattern segment of
# "*" matches exactly one path segment, so "/api/v1/model-candidates/*/promote"
# matches "/api/v1/model-candidates/MDL-001/promote" but not a longer path.
# A route with no session simply cannot reach anything past the middleware, so
# this table only ever decides *which* authenticated caller may proceed.
ROUTE_CAPABILITIES: tuple[tuple[str, str, Capability], ...] = (
    ("GET", "/", Capability.VIEW_MONITORING),
    ("GET", "/prediksi", Capability.CREATE_PREDICTION),
    ("POST", "/operasi-harian", Capability.CREATE_PREDICTION),
    ("POST", "/operasi-harian/*/prediksi", Capability.CREATE_PREDICTION),
    ("GET", "/impor-data-historis", Capability.IMPORT_OPERATIONS),
    ("POST", "/impor-data-historis", Capability.IMPORT_OPERATIONS),
    ("GET", "/contoh-data-riwayat.csv", Capability.IMPORT_OPERATIONS),
    ("POST", "/dataset-versions/*/latih-kandidat-baseline", Capability.MANAGE_MODELS),
    ("GET", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS),
    ("POST", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS),
    ("GET", "/bahan-bakar-aktual", Capability.RECORD_ACTUAL_FUEL),
    ("POST", "/bahan-bakar-aktual", Capability.RECORD_ACTUAL_FUEL),
    ("GET", "/bahan-bakar-aktual-massal", Capability.RECORD_ACTUAL_FUEL),
    ("POST", "/bahan-bakar-aktual-massal", Capability.RECORD_ACTUAL_FUEL),
    ("GET", "/pengelolaan-model", Capability.VIEW_MODELS),
    ("GET", "/model/unggah", Capability.MANAGE_MODELS),
    ("POST", "/model/unggah", Capability.MANAGE_MODELS),
    ("GET", "/model/riwayat", Capability.VIEW_MODELS),
    ("POST", "/kandidat-model/*/promosikan", Capability.MANAGE_MODELS),
    ("GET", "/kandidat-model/*/perbandingan", Capability.VIEW_MODELS),
    ("GET", "/pemantauan/kesehatan-sistem", Capability.VIEW_MONITORING),
    ("GET", "/pemantauan/pergeseran-data", Capability.VIEW_MONITORING),
    ("GET", "/pemantauan/kinerja-model", Capability.VIEW_MONITORING),
    ("GET", "/integrasi-agen", Capability.MANAGE_USERS),
    ("POST", "/integrasi-agen", Capability.MANAGE_USERS),
    ("POST", "/integrasi-agen/*/cabut", Capability.MANAGE_USERS),
    ("GET", "/pengguna", Capability.MANAGE_USERS),
    ("POST", "/pengguna", Capability.MANAGE_USERS),
    ("GET", "/audit", Capability.VIEW_AUDIT),
    ("POST", "/api/v1/daily-operations", Capability.CREATE_PREDICTION),
    ("GET", "/api/v1/daily-operations/*", Capability.CREATE_PREDICTION),
    ("POST", "/api/v1/daily-operations/*/predictions", Capability.CREATE_PREDICTION),
    ("POST", "/api/v1/daily-operations/*/actual-fuel", Capability.RECORD_ACTUAL_FUEL),
    ("POST", "/api/v1/historical-datasets", Capability.IMPORT_OPERATIONS),
    ("GET", "/api/v1/bulk-operation-predictions/template", Capability.IMPORT_OPERATIONS),
    ("POST", "/api/v1/bulk-operation-predictions", Capability.IMPORT_OPERATIONS),
    ("GET", "/api/v1/bulk-actual-fuel/template", Capability.RECORD_ACTUAL_FUEL),
    ("POST", "/api/v1/bulk-actual-fuel", Capability.RECORD_ACTUAL_FUEL),
    ("GET", "/api/v1/dataset-versions/*/daily-operations", Capability.IMPORT_OPERATIONS),
    ("POST", "/api/v1/dataset-versions/*/baseline-candidates", Capability.MANAGE_MODELS),
    ("GET", "/api/v1/model-candidates/*/comparison", Capability.VIEW_MODELS),
    ("POST", "/api/v1/model-candidates/*/promote", Capability.MANAGE_MODELS),
    ("GET", "/api/v1/model-governance-dashboard", Capability.VIEW_MODELS),
    ("GET", "/api/v1/monitoring-dashboard", Capability.VIEW_MONITORING),
    ("GET", "/api/v1/prediction-performance", Capability.VIEW_MONITORING),
    ("POST", "/api/v1/users", Capability.MANAGE_USERS),
    ("GET", "/api/v1/users", Capability.MANAGE_USERS),
    ("GET", "/api/v1/audit-records", Capability.VIEW_AUDIT),
)

# Stands in for the caller before any administrator is provisioned, so the
# original unauthenticated local MVP keeps behaving exactly as it always did.
# See ResolveSession.is_system_provisioned.
_UNPROVISIONED_USER = User(
    user_id="unprovisioned",
    username="sistem",
    full_name="Mode lokal (belum ada akun)",
    role=UserRole.ADMINISTRATOR,
    password_hash="",
    is_active=True,
    created_at=datetime(2020, 1, 1, tzinfo=UTC),
)
_UNPROVISIONED_CALLER = ActiveCaller(user=_UNPROVISIONED_USER, csrf_token="")


class AuthenticationRequiredError(Exception):
    pass


class AuthorizationDeniedError(Exception):
    def __init__(self, capability: Capability) -> None:
        super().__init__(str(capability))
        self.capability = capability


class CsrfValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SecurityGuard:
    """Reads the caller off the request and enforces what that caller may do."""

    def caller_or_none(self, request: Request) -> ActiveCaller | None:
        caller: ActiveCaller | None = getattr(request.state, "caller", None)
        return caller

    def require_caller(self, request: Request) -> ActiveCaller:
        caller = self.caller_or_none(request)
        if caller is None:
            raise AuthenticationRequiredError()
        return caller

    def require(self, request: Request, capability: Capability) -> ActiveCaller:
        caller = self.require_caller(request)
        if not caller.allows(capability):
            raise AuthorizationDeniedError(capability)
        return caller


def is_api_path(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/mcp")


class _SessionMiddleware:
    """Pure ASGI middleware, not ``@app.middleware("http")``.

    Starlette's ``BaseHTTPMiddleware`` (what the decorator form uses) replays
    the request body to the downstream app through a separate queue that a
    direct ``await request.form()`` call in the middleware never feeds, so the
    route handler would see an empty body. Reading the body once here and
    handing the ASGI app a `receive` that replays those exact bytes avoids
    that pitfall entirely.
    """

    def __init__(self, app: ASGIApp, resolve_session: ResolveSession) -> None:
        self.app = app
        self.resolve_session = resolve_session

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        state = scope.setdefault("state", {})

        if not self.resolve_session.is_system_provisioned():
            state["caller"] = _UNPROVISIONED_CALLER
            await self.app(scope, receive, send)
            return

        caller = self.resolve_session.execute(request.cookies.get(SESSION_COOKIE))
        state["caller"] = caller

        downstream_receive = receive
        if _requires_csrf(request):
            body = await request.body()

            async def replay_body() -> Message:
                return {"type": "http.request", "body": body, "more_body": False}

            downstream_receive = replay_body

            supplied = await _supplied_csrf_token(request)
            expected = caller.csrf_token if caller is not None else request.cookies.get(
                CSRF_COOKIE
            )
            if not expected or not supplied or not compare_digest(expected, supplied):
                await _csrf_failure_response(request)(scope, receive, send)
                return

        if not _is_public(request.url.path) and caller is None:
            await _authentication_required_response(request)(scope, receive, send)
            return

        required = _required_capability(request.method, request.url.path)
        if required is not None and caller is not None and not caller.allows(required):
            await _authorization_denied_response(request)(scope, receive, send)
            return

        await self.app(scope, downstream_receive, send)


def install_session_middleware(app: FastAPI, resolve_session: ResolveSession) -> None:
    app.add_middleware(_SessionMiddleware, resolve_session=resolve_session)


def register_security_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationRequiredError)
    async def handle_authentication_required(
        request: Request, _error: AuthenticationRequiredError
    ) -> Response:
        return _authentication_required_response(request)

    @app.exception_handler(AuthorizationDeniedError)
    async def handle_authorization_denied(
        request: Request, _error: AuthorizationDeniedError
    ) -> Response:
        return _authorization_denied_response(request)

    @app.exception_handler(CsrfValidationError)
    async def handle_csrf(request: Request, _error: CsrfValidationError) -> Response:
        return _csrf_failure_response(request)


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _is_public(path: str) -> bool:
    return any(path == public or path.startswith(f"{public}/") for public in _PUBLIC_PATHS)


def _required_capability(method: str, path: str) -> Capability | None:
    path_segments = [segment for segment in path.split("/") if segment != ""]
    for route_method, pattern, capability in ROUTE_CAPABILITIES:
        if route_method != method:
            continue
        pattern_segments = [segment for segment in pattern.split("/") if segment != ""]
        if len(pattern_segments) != len(path_segments):
            continue
        if all(
            pattern_segment in ("*", path_segment)
            for pattern_segment, path_segment in zip(pattern_segments, path_segments, strict=True)
        ):
            return capability
    return None


def _requires_csrf(request: Request) -> bool:
    if request.method in _SAFE_METHODS:
        return False
    content_type = request.headers.get("content-type", "")
    return any(content_type.startswith(form_type) for form_type in _FORM_CONTENT_TYPES)


async def _supplied_csrf_token(request: Request) -> str | None:
    form = await request.form()
    value = form.get(CSRF_FIELD)
    return value if isinstance(value, str) else None


def new_csrf_token() -> str:
    return token_urlsafe(32)


def issue_pre_session_csrf_token(
    request: Request, response: Response, *, token: str | None = None
) -> str:
    """Double-submit token for forms shown before a session exists, such as sign-in."""
    resolved = token or request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    response.set_cookie(
        CSRF_COOKIE,
        resolved,
        httponly=False,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return resolved


def _authentication_required_response(request: Request) -> Response:
    if is_api_path(request.url.path):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "authentication_required",
                    "message": "Silakan masuk terlebih dahulu untuk mengakses layanan ini.",
                }
            },
        )
    destination = quote(request.url.path, safe="")
    return RedirectResponse(
        f"/masuk?tujuan={destination}", status_code=status.HTTP_303_SEE_OTHER
    )


def _authorization_denied_response(request: Request) -> Response:
    message = "Peran Anda tidak memiliki akses ke tindakan ini."
    if is_api_path(request.url.path):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": {"code": "forbidden", "message": message}},
        )
    return _forbidden_page(message)


def _csrf_failure_response(request: Request) -> Response:
    message = (
        "Sesi formulir sudah tidak berlaku. Muat ulang halaman lalu kirim kembali "
        "isian Anda."
    )
    if is_api_path(request.url.path):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": {"code": "csrf_invalid", "message": message}},
        )
    return _forbidden_page(message)


def _forbidden_page(message: str) -> Response:
    from fuel_predictor.delivery.rendering import render_error_page

    return Response(
        content=render_error_page("Akses ditolak", message),
        media_type="text/html; charset=utf-8",
        status_code=status.HTTP_403_FORBIDDEN,
    )
