"""Overview, user administration, and audit pages (Phase 1 of the production plan).

These are the first pages rendered through the new Jinja design system
(ADR 0007) rather than the f-string builders in ``form.py``. Remaining pages
migrate incrementally; see docs/production/implementation-progress.md.
"""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from fuel_predictor.application.identity import CreateUser, ListAuditRecords, ListUsers
from fuel_predictor.application.model_lifecycle import GetModelGovernanceDashboard
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import IdentityValidationError, UserRole

_ROLE_LABELS = {
    UserRole.OPERATOR: "Operator",
    UserRole.MANAGER: "Manajer",
    UserRole.ADMINISTRATOR: "Administrator",
}


def build_dashboard_router(
    get_monitoring_dashboard: GetMonitoringDashboard,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    create_user: CreateUser,
    list_users: ListUsers,
    list_audit_records: ListAuditRecords,
    guard: SecurityGuard,
) -> APIRouter:
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
            )
        )

    @router.get("/pengguna", response_class=HTMLResponse)
    def show_users(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(
            render(
                "pengguna.html",
                caller=caller,
                page_title="Pengguna",
                active_path="/pengguna",
                eyebrow="PENGATURAN",
                page_lead="Kelola akun operator, manajer, dan administrator.",
                users=list_users.execute(),
                role_options=[(role.value, _ROLE_LABELS[role]) for role in UserRole],
                errors=[],
                form_values={},
            )
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
                render(
                    "pengguna.html",
                    caller=caller,
                    page_title="Pengguna",
                    active_path="/pengguna",
                    eyebrow="PENGATURAN",
                    page_lead="Kelola akun operator, manajer, dan administrator.",
                    users=list_users.execute(),
                    role_options=[(role.value, _ROLE_LABELS[role]) for role in UserRole],
                    errors=[{"field": field, "message": message}],
                    form_values=values,
                ),
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
                records=list_audit_records.execute(),
            )
        )

    return router
