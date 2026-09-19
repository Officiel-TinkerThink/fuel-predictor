"""Overview, user administration, and audit pages (Phase 1 of the production plan).

These are the first pages rendered through the new Jinja design system
(ADR 0007) rather than the f-string builders in ``form.py``. Remaining pages
migrate incrementally; see docs/production/implementation-progress.md.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from fuel_predictor.application.identity import (
    ActiveCaller,
    ChangeOwnPassword,
    ChangePassword,
    CreateUser,
    ListAuditRecords,
    ListUsers,
    SetUserActivation,
)
from fuel_predictor.application.model_lifecycle import GetModelGovernanceDashboard
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.application.monitoring_runs import (
    BackupRunRepository,
    MonitoringFreshness,
    MonitoringRunRepository,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import (
    AuditRecord,
    Capability,
    IdentityValidationError,
    UserRole,
)

_ROLE_LABELS = {
    UserRole.OPERATOR: "Operator",
    UserRole.MANAGER: "Manajer",
    UserRole.ADMINISTRATOR: "Administrator",
}

# The day's work, in the order it happens: plan, then report what was burned.
# The overview leads with these so nobody has to hunt the sidebar for them.
_QUICK_ACTIONS = (
    ("Buat prediksi", "/prediksi", Capability.CREATE_PREDICTION),
    ("Catat BBM aktual", "/bahan-bakar-aktual", Capability.RECORD_ACTUAL_FUEL),
    ("Prediksi dari berkas", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS),
)


def build_dashboard_router(
    get_monitoring_dashboard: GetMonitoringDashboard,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    create_user: CreateUser,
    list_users: ListUsers,
    set_user_activation: SetUserActivation,
    change_password: ChangePassword,
    change_own_password: ChangeOwnPassword,
    list_audit_records: ListAuditRecords,
    guard: SecurityGuard,
    monitoring_runs: MonitoringRunRepository,
    backup_runs: BackupRunRepository,
    monitoring_stale_after_hours: int = 26,
) -> APIRouter:
    def _freshness() -> MonitoringFreshness:
        latest = monitoring_runs.latest()
        successful = monitoring_runs.latest_successful()
        return MonitoringFreshness(
            last_success=successful.finished_at if successful else None,
            last_attempt=latest.finished_at if latest else None,
            last_attempt_failed=latest is not None and not latest.succeeded,
            stale_after_hours=monitoring_stale_after_hours,
            now=datetime.now(UTC),
        )

    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def show_overview(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        monitoring = get_monitoring_dashboard.execute()
        governance = get_model_governance_dashboard.execute()
        critical_alerts = [
            alert for alert in monitoring.active_alerts if alert.severity.value == "critical"
        ]
        return HTMLResponse(
            render(
                "ringkasan.html",
                caller=caller,
                page_title="Ringkasan",
                active_path="/",
                eyebrow="IKHTISAR LAYANAN",
                page_lead="Status layanan, model aktif, dan hal yang perlu perhatian hari ini.",
                monitoring=monitoring,
                governance=governance,
                is_healthy=len(critical_alerts) == 0,
                critical_alert_count=len(critical_alerts),
                quick_actions=[
                    {"label": label, "href": href}
                    for label, href, capability in _QUICK_ACTIONS
                    if caller.allows(capability)
                ],
                # A fresh installation has nothing to predict with until history
                # is imported and a candidate trained and promoted. Only the
                # people who can do those steps are walked through them.
                setup_needed=(
                    governance.active_model is None and caller.allows(Capability.IMPORT_OPERATIONS)
                ),
                candidate_count=len(governance.candidate_models),
                freshness=_freshness(),
                last_backup=backup_runs.latest(),
            )
        )

    def _users_page(
        caller: ActiveCaller,
        errors: list[dict[str, str]],
        form_values: dict[str, str],
        notice: str | None = None,
    ) -> str:
        return render(
            "pengguna.html",
            caller=caller,
            page_title="Pengguna",
            active_path="/pengguna",
            eyebrow="PENGATURAN",
            page_lead="Kelola akun operator, manajer, dan administrator.",
            users=list_users.execute(),
            role_options=[(role.value, _ROLE_LABELS[role]) for role in UserRole],
            errors=errors,
            form_values=form_values,
            notice=notice,
        )

    @router.get("/pengguna", response_class=HTMLResponse)
    def show_users(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        notice = {
            "kata-sandi": "Kata sandi diatur ulang. Sesi lama pengguna itu sudah diakhiri.",
            "nonaktif": "Akun dinonaktifkan dan sesinya diakhiri.",
            "aktif": "Akun diaktifkan kembali.",
        }.get(request.query_params.get("pesan", ""))
        return HTMLResponse(_users_page(caller, [], {}, notice))

    @router.post("/pengguna/{user_id}/kata-sandi", response_class=HTMLResponse)
    async def reset_password(user_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        try:
            change_password.execute(
                user_id, str(form.get("password", "")), changed_by=caller.user.username
            )
        except IdentityValidationError as error:
            return HTMLResponse(
                _users_page(caller, [{"field": "reset_password", "message": error.message}], {}),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return RedirectResponse("/pengguna?pesan=kata-sandi", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/pengguna/{user_id}/status", response_class=HTMLResponse)
    async def set_status(user_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        is_active = str(form.get("is_active", "")).lower() == "true"
        # Switching off the account you are signed in with would end this very
        # session mid-request and could leave no administrator at all.
        if user_id == caller.user.user_id and not is_active:
            return HTMLResponse(
                _users_page(
                    caller,
                    [
                        {
                            "field": "status",
                            "message": "Anda tidak dapat menonaktifkan akun Anda sendiri.",
                        }
                    ],
                    {},
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        try:
            set_user_activation.execute(user_id, is_active, changed_by=caller.user.username)
        except IdentityValidationError as error:
            return HTMLResponse(
                _users_page(caller, [{"field": "status", "message": error.message}], {}),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return RedirectResponse(
            f"/pengguna?pesan={'aktif' if is_active else 'nonaktif'}",
            status_code=status.HTTP_303_SEE_OTHER,
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

    @router.post("/pengguna", response_class=HTMLResponse)
    async def submit_user(request: Request) -> Response:
        caller = guard.require_caller(request)
        form = await request.form()
        values = {
            "username": str(form.get("username", "")),
            "full_name": str(form.get("full_name", "")),
            "role": str(form.get("role", UserRole.OPERATOR.value)),
        }
        try:
            create_user.execute(
                username=values["username"],
                full_name=values["full_name"],
                password=str(form.get("password", "")),
                role=UserRole(values["role"]),
                created_by=caller.user.username,
            )
        except (IdentityValidationError, ValueError) as error:
            message = error.message if isinstance(error, IdentityValidationError) else str(error)
            field = error.field if isinstance(error, IdentityValidationError) else "role"
            return HTMLResponse(
                _users_page(caller, [{"field": field, "message": message}], values),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return RedirectResponse("/pengguna", status_code=status.HTTP_303_SEE_OTHER)

    @router.get("/audit", response_class=HTMLResponse)
    def show_audit(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(
            render(
                "audit.html",
                caller=caller,
                page_title="Catatan Audit",
                active_path="/audit",
                eyebrow="PENGATURAN",
                page_lead="Riwayat masuk, tindakan istimewa, dan hasilnya.",
                records=[_audit_row(record) for record in list_audit_records.execute()],
            )
        )

    return router


# What each recorded action means, in words. The code itself stays on the
# page in small type so a log line can still be matched against it.
_ACTION_LABELS = {
    "sign_in_succeeded": "Masuk berhasil",
    "sign_in_failed": "Masuk gagal",
    "sign_out": "Keluar",
    "password_changed": "Kata sandi diubah",
    "user_created": "Pengguna dibuat",
    "user_activated": "Pengguna diaktifkan",
    "model_rollback_requested": "Pengembalian model diminta",
    "agent_credential_issued": "Kredensial agen diterbitkan",
    "agent_credential_revoked": "Kredensial agen dicabut",
    "agent_client_registered": "Klien agen mendaftar",
    "agent_consent_granted": "Izin agen diberikan",
    "agent_grant_issued": "Akses agen diberikan",
    "agent_grant_revoked": "Akses agen dicabut",
    "mcp_rate_limited": "Agen melebihi batas laju",
}
_ACTOR_KIND_LABELS = {"user": "Pengguna", "agent": "Agen", "system": "Sistem"}
_DETAIL_LABELS = {
    "reason": "alasan",
    "role": "peran",
    "note": "catatan",
    "client_id": "klien",
    "scopes": "cakupan",
    "username": "pengguna",
}


def _action_label(action: str) -> str:
    if action in _ACTION_LABELS:
        return _ACTION_LABELS[action]
    if action.startswith("mcp_tool:"):
        return f"Alat agen {action.removeprefix('mcp_tool:')}"
    return action.replace("_", " ").capitalize()


def _audit_row(record: AuditRecord) -> dict[str, object]:
    return {
        "occurred_at": record.occurred_at,
        "actor": record.actor,
        "actor_kind": _ACTOR_KIND_LABELS.get(record.actor_kind, record.actor_kind),
        "action": record.action,
        "action_label": _action_label(record.action),
        "subject": record.subject,
        "outcome": record.outcome.value,
        "details": [
            (_DETAIL_LABELS.get(key, key), value)
            for key, value in record.details.items()
            if value not in (None, "")
        ],
    }
