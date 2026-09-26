"""Sign-in, sign-out, and user/audit administration endpoints (ADR 0008)."""

from urllib.parse import urlparse

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from fuel_predictor.application.identity import (
    CreateUser,
    ListAuditRecords,
    ListUsers,
    PasswordResetTokenInvalidError,
    RequestPasswordReset,
    ResetPasswordWithToken,
    SignIn,
    SignInFailedError,
    SignOut,
)
from fuel_predictor.delivery.rendering import render_error_page, render_standalone
from fuel_predictor.delivery.security import (
    SESSION_COOKIE,
    SecurityGuard,
    clear_session_cookie,
    issue_pre_session_csrf_token,
    new_csrf_token,
    set_session_cookie,
)
from fuel_predictor.domain.identity import (
    AuditRecord,
    Capability,
    IdentityValidationError,
    User,
    UserRole,
)


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    full_name: str
    email: str | None = None
    password: str  # the rules (12+ characters) are the domain's, named with the others
    role: UserRole


class UserResponse(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: str | None
    role: UserRole
    is_active: bool


class UserListResponse(BaseModel):
    users: list[UserResponse]


class AuditRecordResponse(BaseModel):
    audit_id: str
    occurred_at: str
    actor: str
    actor_kind: str
    action: str
    outcome: str
    subject: str | None
    details: dict[str, str | int | float | bool | None]


class AuditListResponse(BaseModel):
    records: list[AuditRecordResponse]


# Why someone is back at the sign-in page, when the reason was their own doing.
# (tone, words): a done thing is good news; an ended session is a heads-up.
_SIGN_IN_NOTICES = {
    "kata-sandi": (
        "success",
        "Kata sandi Anda sudah diubah. Masuk lagi dengan kata sandi yang baru.",
    ),
    "atur-ulang": ("success", "Kata sandi baru tersimpan. Masuk dengan kata sandi itu."),
    "sesi": (
        "warning",
        "Sesi Anda sudah berakhir, jadi isian tadi belum terkirim. Masuk lagi, lalu kirim "
        "ulang formulirnya.",
    ),
}


def build_authentication_router(
    sign_in: SignIn,
    sign_out: SignOut,
    create_user: CreateUser,
    list_users: ListUsers,
    list_audit_records: ListAuditRecords,
    guard: SecurityGuard,
    cookies_require_https: bool,
    *,
    request_password_reset: RequestPasswordReset,
    reset_password: ResetPasswordWithToken,
    reset_mail_configured: bool,
    public_url: str | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/masuk", response_class=HTMLResponse)
    def show_sign_in(request: Request, tujuan: str = "/", pesan: str = "") -> Response:
        if guard.caller_or_none(request) is not None:
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        token = request.cookies.get("fp_csrf") or new_csrf_token()
        response = HTMLResponse(
            render_standalone(
                "masuk.html",
                csrf_token=token,
                destination=_safe_destination(tujuan),
                username="",
                error=None,
                notice=_SIGN_IN_NOTICES.get(pesan),
            )
        )
        issue_pre_session_csrf_token(request, response, token=token)
        return response

    @router.post("/masuk", response_class=HTMLResponse)
    async def submit_sign_in(request: Request) -> Response:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        destination = _safe_destination(str(form.get("tujuan", "/")))
        try:
            session = sign_in.execute(username, password)
        except SignInFailedError as error:
            failed = HTMLResponse(
                render_standalone(
                    "masuk.html",
                    csrf_token=request.cookies.get("fp_csrf", ""),
                    destination=destination,
                    username=username,
                    error=error.message,
                    notice=None,
                ),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
            return failed

        response = RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)
        secure = cookies_require_https or request.url.scheme == "https"
        set_session_cookie(response, session.session_token, secure=secure)
        return response

    # --- Forgotten passwords ----------------------------------------------------

    def _forgot_page(request: Request, *, requested: bool) -> Response:
        token = request.cookies.get("fp_csrf") or new_csrf_token()
        response = HTMLResponse(
            render_standalone(
                "lupa-kata-sandi.html",
                csrf_token=token,
                available=reset_mail_configured,
                requested=requested,
            )
        )
        issue_pre_session_csrf_token(request, response, token=token)
        return response

    @router.get("/lupa-kata-sandi", response_class=HTMLResponse)
    def show_forgot_password(request: Request) -> Response:
        return _forgot_page(request, requested=False)

    @router.post("/lupa-kata-sandi", response_class=HTMLResponse)
    async def submit_forgot_password(request: Request) -> Response:
        if not reset_mail_configured:
            return _forgot_page(request, requested=False)
        form = await request.form()
        origin = public_url or str(request.base_url).rstrip("/")
        request_password_reset.execute(
            str(form.get("identifier", "")),
            link_for=lambda raw: f"{origin}/atur-ulang-kata-sandi?token={raw}",
        )
        # The same page whatever happened: nothing here says whether the
        # account exists or has an address.
        return _forgot_page(request, requested=True)

    def _reset_page(request: Request, token: str, username: str, error: str | None) -> Response:
        csrf = request.cookies.get("fp_csrf") or new_csrf_token()
        response = HTMLResponse(
            render_standalone(
                "atur-ulang-kata-sandi.html",
                csrf_token=csrf,
                token=token,
                username=username,
                error=error,
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if error else status.HTTP_200_OK,
        )
        issue_pre_session_csrf_token(request, response, token=csrf)
        return response

    def _link_spent() -> HTMLResponse:
        return HTMLResponse(
            render_error_page(
                "Tautan tidak berlaku",
                "Tautan ini sudah dipakai, kedaluwarsa, atau tidak dikenal. Minta tautan baru "
                "dari halaman Lupa kata sandi.",
            ),
            status_code=status.HTTP_410_GONE,
        )

    @router.get("/atur-ulang-kata-sandi", response_class=HTMLResponse)
    def show_reset_password(request: Request, token: str = "") -> Response:
        try:
            user = reset_password.inspect(token)
        except PasswordResetTokenInvalidError:
            return _link_spent()
        return _reset_page(request, token, user.username, None)

    @router.post("/atur-ulang-kata-sandi", response_class=HTMLResponse)
    async def submit_reset_password(request: Request) -> Response:
        form = await request.form()
        token = str(form.get("token", ""))
        try:
            reset_password.execute(token, str(form.get("new_password", "")))
        except PasswordResetTokenInvalidError:
            return _link_spent()
        except IdentityValidationError as error:
            user = reset_password.inspect(token)
            return _reset_page(request, token, user.username, error.message)
        return RedirectResponse("/masuk?pesan=atur-ulang", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/keluar")
    async def submit_sign_out(request: Request) -> Response:
        caller = guard.caller_or_none(request)
        token = request.cookies.get(SESSION_COOKIE)
        if caller is not None and token:
            sign_out.execute(token, caller.user.username)
        response = RedirectResponse("/masuk", status_code=status.HTTP_303_SEE_OTHER)
        clear_session_cookie(response)
        return response

    @router.post("/api/v1/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    def create_user_endpoint(request: Request, payload: CreateUserRequest) -> UserResponse:
        actor = guard.require(request, Capability.MANAGE_USERS)
        user = create_user.execute(
            username=payload.username,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            created_by=actor.user.username,
        )
        return _user_response(user)

    @router.get("/api/v1/users", response_model=UserListResponse)
    def list_users_endpoint(request: Request) -> UserListResponse:
        guard.require(request, Capability.MANAGE_USERS)
        return UserListResponse(users=[_user_response(user) for user in list_users.execute()])

    @router.get("/api/v1/audit-records", response_model=AuditListResponse)
    def list_audit_endpoint(request: Request, limit: int = 200) -> AuditListResponse:
        guard.require(request, Capability.VIEW_AUDIT)
        return AuditListResponse(
            records=[_audit_response(record) for record in list_audit_records.execute(limit)]
        )

    return router


def register_identity_error_handlers(app: object) -> None:
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)

    @app.exception_handler(IdentityValidationError)
    async def handle_identity_validation(
        _request: Request, error: IdentityValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "errors": [
                    {"field": problem.field, "message": problem.message}
                    for problem in error.problems
                ]
            },
        )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


def _audit_response(record: AuditRecord) -> AuditRecordResponse:
    return AuditRecordResponse(
        audit_id=record.audit_id,
        occurred_at=record.occurred_at.isoformat(),
        actor=record.actor,
        actor_kind=record.actor_kind,
        action=record.action,
        outcome=str(record.outcome),
        subject=record.subject,
        details=dict(record.details),
    )


def _safe_destination(value: str) -> str:
    """Only allow same-site paths, so `tujuan` cannot become an open redirect."""
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    return value
