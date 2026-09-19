"""Monitoring pages, split into the plan's three views (ADR 0007, self-service-production-plan.md).

Kesehatan Sistem, Pergeseran Data, and Kinerja Model replace the single
combined `/pemantauan-operasi` page. Kinerja Model also absorbs the old
`/kinerja-prediksi` full-history performance report, since the plan's nav
only names one "Kinerja Model" item and the two features serve the same
question (is the model performing well) at different time horizons.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.actual_fuel import GetPredictionPerformance
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.application.monitoring_runs import (
    BackupRunRepository,
    MonitoringFreshness,
    MonitoringRunRepository,
)
from fuel_predictor.delivery.rendering import format_datetime, format_decimal, render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.alert_remediation import remediation_for, urgency_for
from fuel_predictor.domain.monitoring import (
    MonitoringAlert,
    MonitoringAlertKind,
    MonitoringAlertSeverity,
    RollingErrorPoint,
)


def build_monitoring_pages_router(
    get_monitoring_dashboard: GetMonitoringDashboard,
    get_prediction_performance: GetPredictionPerformance,
    guard: SecurityGuard,
    monitoring_runs: MonitoringRunRepository,
    backup_runs: BackupRunRepository,
    monitoring_stale_after_hours: int = 26,
    alert_channel_configured: bool = False,
) -> APIRouter:
    router = APIRouter()

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

    @router.get("/pemantauan/kesehatan-sistem", response_class=HTMLResponse)
    def show_system_health(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        dashboard = get_monitoring_dashboard.execute()
        return HTMLResponse(
            render(
                "kesehatan-sistem.html",
                caller=caller,
                page_title="Kesehatan Sistem",
                active_path="/pemantauan/kesehatan-sistem",
                eyebrow="PEMANTAUAN LOKAL",
                page_lead="Status layanan, kualitas data, dan hal yang perlu perhatian.",
                active_alerts=dashboard.active_alerts,
                alert_groups=group_alerts(dashboard.active_alerts),
                unresolved_data_quality_issue_count=dashboard.unresolved_data_quality_issue_count,
                unresolved_data_quality_issues=dashboard.unresolved_data_quality_issues,
                dataset_validation_summaries=dashboard.dataset_validation_summaries,
                missing_actual_predictions=dashboard.missing_actual_predictions,
                missing_actual_prediction_count=dashboard.missing_actual_prediction_count,
                missing_actual_after_days=dashboard.missing_actual_after_days,
                freshness=_freshness(),
                last_backup=backup_runs.latest(),
                # Whether anyone is actually told about these alerts. "No
                # alerts fired" and "nobody is listening" must not read the
                # same on the page any more than they do in the log.
                alert_channel_configured=alert_channel_configured,
            )
        )

    @router.get("/pemantauan/pergeseran-data", response_class=HTMLResponse)
    def show_data_drift(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        dashboard = get_monitoring_dashboard.execute()
        return HTMLResponse(
            render(
                "pergeseran-data.html",
                caller=caller,
                page_title="Pergeseran Data",
                active_path="/pemantauan/pergeseran-data",
                eyebrow="PEMANTAUAN LOKAL",
                page_lead=(
                    "Perbandingan distribusi fitur referensi terhadap fitur prediksi terkini."
                ),
                drift=dashboard.feature_drift,
            )
        )

    @router.get("/pemantauan/kinerja-model", response_class=HTMLResponse)
    def show_model_performance(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        dashboard = get_monitoring_dashboard.execute()
        performance = get_prediction_performance.execute()
        return HTMLResponse(
            render(
                "kinerja-model.html",
                caller=caller,
                page_title="Kinerja Model",
                active_path="/pemantauan/kinerja-model",
                eyebrow="EVALUASI MODEL",
                page_lead="Kinerja model aktif diukur dari bahan bakar aktual yang tercocokkan.",
                performance=performance,
                rolling_error_trend=dashboard.rolling_error_trend,
                trend_chart=trend_chart(
                    dashboard.rolling_error_trend, dashboard.degradation_mae_threshold_liters
                ),
                rolling_error_window=dashboard.rolling_error_window,
                category_degradation=dashboard.category_degradation,
                degradation_mae_threshold_liters=dashboard.degradation_mae_threshold_liters,
            )
        )

    return router


# The kinds in words. The code stays out of sight: nobody acts on "missing_actual".
ALERT_KIND_LABELS: dict[MonitoringAlertKind, str] = {
    MonitoringAlertKind.DATA_QUALITY: "Baris impor perlu diperbaiki",
    MonitoringAlertKind.MISSING_ACTUAL: "Aktual belum dicatat",
    MonitoringAlertKind.FEATURE_DRIFT: "Operasi berbeda dari data latih",
    MonitoringAlertKind.MODEL_DEGRADATION: "Kinerja model menurun",
}


def alert_kind_label(kind: MonitoringAlertKind) -> str:
    return ALERT_KIND_LABELS.get(kind, kind.value)


def group_alerts(alerts: Sequence[MonitoringAlert]) -> list[dict[str, object]]:
    """One group per kind, worst severity first, carrying the remediation
    once - three overdue operations are one thing to do, not three."""
    groups: dict[MonitoringAlertKind, list[MonitoringAlert]] = {}
    for alert in alerts:
        groups.setdefault(alert.kind, []).append(alert)
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            0 if any(a.severity.value == "critical" for a in item[1]) else 1,
            ALERT_KIND_LABELS.get(item[0], item[0].value),
        ),
    )
    result: list[dict[str, object]] = []
    for kind, members in ordered:
        critical = any(a.severity.value == "critical" for a in members)
        worst = MonitoringAlertSeverity.CRITICAL if critical else MonitoringAlertSeverity.WARNING
        result.append(
            {
                "label": alert_kind_label(kind),
                "critical": critical,
                "urgency": urgency_for(worst),
                "remediation": remediation_for(kind),
                "messages": [a.message for a in members],
            }
        )
    return result


# Plot geometry for the rolling-error line: a fixed viewBox the CSS scales,
# with room on the left for the value labels and below for the dates.
_CHART_WIDTH = 640
_CHART_HEIGHT = 200
_PAD_LEFT, _PAD_RIGHT, _PAD_TOP, _PAD_BOTTOM = 48, 16, 12, 28


def trend_chart(
    points: Sequence[RollingErrorPoint], threshold_liters: float
) -> dict[str, object] | None:
    """Coordinates for the rolling-MAE line, or None when there is nothing to draw.

    The y range always includes zero and the degradation threshold, so the line
    sits against the level that matters rather than filling the box whatever
    its values; the page's table remains the exact reading of the same points.
    """
    if not points:
        return None
    top = max(max(point.mae_liters for point in points), threshold_liters) * 1.15 or 1.0
    plot_width = _CHART_WIDTH - _PAD_LEFT - _PAD_RIGHT
    plot_height = _CHART_HEIGHT - _PAD_TOP - _PAD_BOTTOM
    step = plot_width / (len(points) - 1) if len(points) > 1 else 0

    def y_of(value: float) -> float:
        return round(_PAD_TOP + plot_height - (value / top) * plot_height, 1)

    plotted = [
        {
            "x": round(_PAD_LEFT + index * step, 1) if step else _PAD_LEFT + plot_width / 2,
            "y": y_of(point.mae_liters),
            "label": (
                f"{format_datetime(point.observed_at)}: MAE {format_decimal(point.mae_liters)} L "
                f"({point.matched_record_count} data cocok)"
            ),
            "value": format_decimal(point.mae_liters),
        }
        for index, point in enumerate(points)
    ]
    return {
        "width": _CHART_WIDTH,
        "height": _CHART_HEIGHT,
        "points": plotted,
        "path": " ".join(f"{p['x']},{p['y']}" for p in plotted),
        "baseline_y": y_of(0),
        "threshold_y": y_of(threshold_liters),
        "threshold_label": f"Ambang {format_decimal(threshold_liters)} L",
        "top_label": f"{format_decimal(round(top, 1))} L",
        "first_date": format_datetime(points[0].observed_at)[:10],
        "last_date": format_datetime(points[-1].observed_at)[:10],
        "left": _PAD_LEFT,
        "right": _CHART_WIDTH - _PAD_RIGHT,
        "bottom": _CHART_HEIGHT - _PAD_BOTTOM,
        "above_threshold": points[-1].mae_liters > threshold_liters,
    }
