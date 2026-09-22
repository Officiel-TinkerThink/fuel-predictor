"""Overview, user administration, and audit pages (Phase 1 of the production plan).

These are the first pages rendered through the new Jinja design system
(ADR 0007) rather than the f-string builders in ``form.py``. Remaining pages
migrate incrementally; see docs/production/implementation-progress.md.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.actual_fuel import ListOperationsAwaitingActualFuel
from fuel_predictor.application.identity import ListAuditRecords
from fuel_predictor.application.model_lifecycle import GetModelGovernanceDashboard
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.application.monitoring_runs import (
    BackupRunRepository,
    MonitoringFreshness,
    MonitoringRunRepository,
)
from fuel_predictor.delivery.audit_view import audit_row
from fuel_predictor.delivery.listing import ListingQuery, SortOption, paginate
from fuel_predictor.delivery.monitoring_pages import ALERT_KIND_LABELS
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.identity import Capability

# The trail pages over its newest rows in memory; a search reaches the rest.
_AUDIT_MAX = 5000
_AUDIT_SORTS = (
    SortOption("waktu", "Waktu", lambda r: r["occurred_at"]),
    SortOption("pelaku", "Pelaku", lambda r: r["actor"], default_direction="asc"),
    SortOption("tindakan", "Tindakan", lambda r: r["action_label"], default_direction="asc"),
)

# The day's work, in the order it happens: plan, then report what was burned.
# The overview leads with these so nobody has to hunt the sidebar for them.
_QUICK_ACTIONS = (
    ("Buat prediksi", "/prediksi", Capability.CREATE_PREDICTION),
    ("Catat BBM aktual", "/bahan-bakar-aktual", Capability.RECORD_ACTUAL_FUEL),
    ("Prediksi massal dari berkas", "/prediksi-operasi-massal", Capability.IMPORT_OPERATIONS),
)


def build_dashboard_router(
    get_monitoring_dashboard: GetMonitoringDashboard,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    list_audit_records: ListAuditRecords,
    list_awaiting_actual: ListOperationsAwaitingActualFuel,
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
        can_monitor = caller.allows(Capability.VIEW_MONITORING)
        return HTMLResponse(
            render(
                "ringkasan.html",
                caller=caller,
                page_title="Ringkasan",
                active_path="/",
                eyebrow="IKHTISAR LAYANAN" if can_monitor else "HARI INI",
                page_lead=(
                    "Status layanan, model aktif, dan hal yang perlu perhatian hari ini."
                    if can_monitor
                    else "Buat estimasi untuk operasi hari ini, dan catat BBM aktual "
                    "untuk yang sudah selesai."
                ),
                # An operator's overview is their two jobs, with the operations
                # still waiting for actual fuel; the health of the model and
                # the service is the administrator's to read.
                can_monitor=can_monitor,
                awaiting=(
                    ()
                    if can_monitor or not caller.allows(Capability.RECORD_ACTUAL_FUEL)
                    else list_awaiting_actual.execute()[:8]
                ),
                monitoring=monitoring,
                governance=governance,
                is_healthy=len(critical_alerts) == 0,
                critical_alert_count=len(critical_alerts),
                alert_kind_labels=ALERT_KIND_LABELS,
                quick_actions=[
                    {"label": label, "href": href}
                    for label, href, capability in _QUICK_ACTIONS
                    if caller.allows(capability)
                ],
                # A fresh installation has nothing to predict with until history
                # is imported and a candidate trained and promoted. Only the
                # people who can do those steps are walked through them.
                setup_needed=(
                    governance.active_model is None and caller.allows(Capability.MANAGE_MODELS)
                ),
                candidate_count=len(governance.candidate_models),
                freshness=_freshness(),
                last_backup=backup_runs.latest(),
            )
        )

    @router.get("/audit", response_class=HTMLResponse)
    def show_audit(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        outcome = request.query_params.get("hasil", "")
        rows = [audit_row(record) for record in list_audit_records.execute(_AUDIT_MAX)]
        if outcome in ("succeeded", "failed", "denied"):
            rows = [row for row in rows if row["outcome"] == outcome]
        listing = paginate(
            rows,
            ListingQuery.from_params(request.query_params, extra_keys=("hasil",)),
            search=lambda r: [
                str(r["actor"]),
                str(r["action_label"]),
                str(r["action"]),
                str(r["subject"] or ""),
            ],
            sorts=_AUDIT_SORTS,
            default_sort="waktu",
        )
        return HTMLResponse(
            render(
                "audit.html",
                caller=caller,
                page_title="Catatan Audit",
                active_path="/audit",
                eyebrow="PENGATURAN",
                page_lead=(
                    "Kejadian penting: operasi direncanakan, aktual dicatat, berkas diimpor, "
                    "model berganti, akun diubah, dan percobaan masuk yang gagal."
                ),
                listing=listing,
                outcome=outcome,
            )
        )

    return router
