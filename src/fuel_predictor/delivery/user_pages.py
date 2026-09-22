"""Accounts, as an administrator runs them, and one's own password (ADR 0007).

Pengguna is a directory: who is active, when each person last signed in,
how much they planned and reported lately, and a page per person with the
profile, the account actions, and their trail. Kata Sandi is the one
account page everyone has.
"""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from fuel_predictor.application.identity import (
    ActiveCaller,
    ChangeOwnPassword,
    ChangePassword,
    CreateUser,
    SetUserActivation,
)
from fuel_predictor.application.user_directory import (
    GetUserDetail,
    GetUserDirectory,
    UpdateUserProfile,
)
from fuel_predictor.delivery.audit_view import audit_row
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import IdentityValidationError, UserRole

_ROLE_LABELS = {
    UserRole.OPERATOR: "Operator",
    UserRole.ADMINISTRATOR: "Administrator",
}
_ROLE_OPTIONS = [(role.value, _ROLE_LABELS[role]) for role in UserRole]

# What a redirect back to the page says happened.
_NOTICES = {
    "dibuat": "Pengguna baru tersimpan. Sampaikan kata sandi awalnya secara aman.",
    "profil": "Profil tersimpan.",
    "kata-sandi": "Kata sandi diatur ulang. Sesi lama pengguna itu sudah diakhiri.",
    "nonaktif": "Akun dinonaktifkan dan sesinya diakhiri.",
    "aktif": "Akun diaktifkan kembali.",
}


def build_user_pages_router(
    *,
    create_user: CreateUser,
    get_user_directory: GetUserDirectory,
    get_user_detail: GetUserDetail,
    update_user_profile: UpdateUserProfile,
    set_user_activation: SetUserActivation,
    change_password: ChangePassword,
    change_own_password: ChangeOwnPassword,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    # --- Directory ------------------------------------------------------------------

    def _directory_page(
        caller: ActiveCaller,
        *,
        errors: list[dict[str, str]] | None = None,
        form_values: dict[str, str] | None = None,
        notice: str | None = None,
    ) -> str:
        directory = get_user_directory.execute()
        return render(
            "pengguna.html",
            caller=caller,
            page_title="Pengguna",
            active_path="/pengguna",
            eyebrow="PENGATURAN",
            page_lead="Siapa yang memakai aplikasi ini, dan apa yang mereka kerjakan belakangan.",
            directory=directory,
            role_labels=_ROLE_LABELS,
            role_options=_ROLE_OPTIONS,
            errors=errors or [],
            form_values=form_values or {},
            # A failed "Tambah pengguna" comes back with its dialog open.
            add_dialog_open=bool(errors),
            notice=notice,
        )

    @router.get("/pengguna", response_class=HTMLResponse)
    def show_directory(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        notice = _NOTICES.get(request.query_params.get("pesan", ""))
        return HTMLResponse(_directory_page(caller, notice=notice))

    @router.post("/pengguna", response_class=HTMLResponse)
    async def submit_user(request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        values = {
            "username": str(form.get("username", "")),
            "full_name": str(form.get("full_name", "")),
            "email": str(form.get("email", "")),
            "role": str(form.get("role", UserRole.OPERATOR.value)),
        }
        try:
            created = create_user.execute(
                username=values["username"],
                full_name=values["full_name"],
                email=values["email"],
                password=str(form.get("password", "")),
                role=UserRole(values["role"]),
                created_by=caller.user.username,
            )
        except (IdentityValidationError, ValueError) as error:
            message = error.message if isinstance(error, IdentityValidationError) else str(error)
            field = error.field if isinstance(error, IdentityValidationError) else "role"
            return HTMLResponse(
                _directory_page(
                    caller, errors=[{"field": field, "message": message}], form_values=values
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return RedirectResponse(
            f"/pengguna/{created.user_id}?pesan=dibuat", status_code=status.HTTP_303_SEE_OTHER
        )

    # --- One person -----------------------------------------------------------------

    def _detail_page(
        caller: ActiveCaller,
        user_id: str,
        *,
        errors: list[dict[str, str]] | None = None,
        notice: str | None = None,
    ) -> HTMLResponse:
        try:
            detail = get_user_detail.execute(user_id)
        except IdentityValidationError:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Pengguna tidak ditemukan",
                    active_path="/pengguna",
                    message="Tidak ada akun dengan alamat itu.",
                    back_href="/pengguna",
                    back_label="Kembali ke daftar pengguna",
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(
            render(
                "pengguna-detail.html",
                caller=caller,
                page_title=detail.user.full_name,
                active_path="/pengguna",
                eyebrow="PENGATURAN",
                breadcrumbs=[
                    {"label": "Pengguna", "href": "/pengguna"},
                    {"label": detail.user.full_name, "href": None},
                ],
                detail=detail,
                role_labels=_ROLE_LABELS,
                role_options=_ROLE_OPTIONS,
                trail=[audit_row(record) for record in detail.trail],
                errors=errors or [],
                notice=notice,
                is_self=detail.user.user_id == caller.user.user_id,
            ),
            status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK),
        )

    @router.get("/pengguna/{user_id}", response_class=HTMLResponse)
    def show_user(user_id: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        notice = _NOTICES.get(request.query_params.get("pesan", ""))
        return _detail_page(caller, user_id, notice=notice)

    @router.post("/pengguna/{user_id}/profil", response_class=HTMLResponse)
    async def update_profile(user_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        try:
            update_user_profile.execute(
                user_id,
                full_name=str(form.get("full_name", "")),
                email=str(form.get("email", "")),
                role=UserRole(str(form.get("role", caller.user.role.value))),
                changed_by=caller.user,
            )
        except (IdentityValidationError, ValueError) as error:
            message = error.message if isinstance(error, IdentityValidationError) else str(error)
            field = error.field if isinstance(error, IdentityValidationError) else "role"
            return _detail_page(caller, user_id, errors=[{"field": field, "message": message}])
        return RedirectResponse(
            f"/pengguna/{user_id}?pesan=profil", status_code=status.HTTP_303_SEE_OTHER
        )

    @router.post("/pengguna/{user_id}/kata-sandi", response_class=HTMLResponse)
    async def reset_password(user_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        try:
            change_password.execute(
                user_id, str(form.get("password", "")), changed_by=caller.user.username
            )
        except IdentityValidationError as error:
            return _detail_page(
                caller, user_id, errors=[{"field": "reset_password", "message": error.message}]
            )
        return RedirectResponse(
            f"{_back_to(form.get('kembali'), user_id)}?pesan=kata-sandi",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @router.post("/pengguna/{user_id}/status", response_class=HTMLResponse)
    async def set_status(user_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        is_active = str(form.get("is_active", "")).lower() == "true"
        # Switching off the account you are signed in with would end this very
        # session mid-request and could leave no administrator at all.
        if user_id == caller.user.user_id and not is_active:
            return _detail_page(
                caller,
                user_id,
                errors=[
                    {
                        "field": "status",
                        "message": "Anda tidak dapat menonaktifkan akun Anda sendiri.",
                    }
                ],
            )
        try:
            set_user_activation.execute(user_id, is_active, changed_by=caller.user.username)
        except IdentityValidationError as error:
            return _detail_page(
                caller, user_id, errors=[{"field": "status", "message": error.message}]
            )
        outcome = "aktif" if is_active else "nonaktif"
        return RedirectResponse(
            f"{_back_to(form.get('kembali'), user_id)}?pesan={outcome}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # --- Own password ---------------------------------------------------------------

    def _own_password_page(caller: ActiveCaller, errors: list[dict[str, str]]) -> str:
        return render(
            "kata-sandi.html",
            caller=caller,
            page_title="Ubah Kata Sandi",
            active_path="/kata-sandi",
            eyebrow="AKUN SAYA",
            page_lead=(
                "Setelah diubah, semua sesi Anda diakhiri dan Anda masuk lagi dengan kata "
                "sandi baru."
            ),
            errors=errors,
        )

    @router.get("/kata-sandi", response_class=HTMLResponse)
    def show_own_password(request: Request) -> HTMLResponse:
        return HTMLResponse(_own_password_page(guard.require_caller(request), []))

    @router.post("/kata-sandi", response_class=HTMLResponse)
    async def submit_own_password(request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        try:
            change_own_password.execute(
                caller.user.user_id,
                str(form.get("current_password", "")),
                str(form.get("new_password", "")),
            )
        except IdentityValidationError as error:
            field = "new_password" if error.field == "password" else error.field
            return HTMLResponse(
                _own_password_page(caller, [{"field": field, "message": error.message}]),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        # Every session ended with the old password, this one included, so
        # the sign-in page is where the person lands - told why.
        return RedirectResponse("/masuk?pesan=kata-sandi", status_code=status.HTTP_303_SEE_OTHER)

    return router


def _back_to(value: object, user_id: str) -> str:
    """Where a row action returns to: the directory when it came from there,
    otherwise the person's page. Anything else is ignored, never followed."""
    return "/pengguna" if value == "/pengguna" else f"/pengguna/{user_id}"
