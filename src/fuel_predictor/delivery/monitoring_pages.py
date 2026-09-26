"""Monitoring pages, split into the plan's three views (ADR 0007, self-service-production-plan.md).

Kesehatan Sistem, Pergeseran Data, and Kinerja Model replace the single
combined `/pemantauan-operasi` page. Kinerja Model also absorbs the old
`/kinerja-prediksi` full-history performance report, since the plan's nav
only names one "Kinerja Model" item and the two features serve the same
question (is the model performing well) at different time horizons.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.actual_fuel import GetPredictionPerformance
from fuel_predictor.application.monitoring import GetMonitoringDashboard, MonitoringDashboard
from fuel_predictor.application.monitoring_runs import (
    BackupRunRepository,
    MonitoringFreshness,
    MonitoringRunRepository,
)
from fuel_predictor.delivery.rendering import format_datetime, format_decimal, render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.alert_remediation import remediation_for, urgency_for
from fuel_predictor.domain.monitoring import (
    FeatureDriftSummary,
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
                page_lead="Apa yang perlu ditangani, dengan tombol untuk menanganinya.",
                tasks=health_tasks(dashboard),
                checks=health_checks(dashboard),
                unresolved_data_quality_issues=dashboard.unresolved_data_quality_issues,
                dataset_validation_summaries=dashboard.dataset_validation_summaries,
                missing_actual_predictions=dashboard.missing_actual_predictions,
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
                page_lead=(
                    "Setiap model diukur dari prediksinya sendiri yang sudah punya bahan bakar "
                    "aktual."
                ),
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
    MonitoringAlertKind.VEHICLE_TAXONOMY: "Penggolongan kendaraan berubah",
}


def alert_kind_label(kind: MonitoringAlertKind) -> str:
    return ALERT_KIND_LABELS.get(kind, kind.value)


@dataclass(frozen=True, slots=True)
class HealthAction:
    label: str
    href: str
    primary: bool = False


@dataclass(frozen=True, slots=True)
class HealthTask:
    """One thing to do, however many alerts it gathers: three overdue
    operations are one job, done with one sheet."""

    kind: str
    title: str
    critical: bool
    urgency: str
    # What the alerts found, when they say more than the title does.
    findings: tuple[str, ...]
    # The full steps, kept from the alert texts; folded on the page.
    remediation: str
    actions: tuple[HealthAction, ...]


# Missing actuals are filled by sheet; the page shows those steps itself.
_ACTIONS: dict[MonitoringAlertKind, tuple[HealthAction, ...]] = {
    MonitoringAlertKind.MODEL_DEGRADATION: (
        HealthAction("Bandingkan dan ganti model", "/pengelolaan-model", primary=True),
        HealthAction("Lihat kinerja model", "/pemantauan/kinerja-model"),
    ),
    MonitoringAlertKind.FEATURE_DRIFT: (
        HealthAction("Lihat pergeseran data", "/pemantauan/pergeseran-data", primary=True),
    ),
    MonitoringAlertKind.DATA_QUALITY: (
        HealthAction("Impor ulang data historis", "/impor-data-historis", primary=True),
    ),
    MonitoringAlertKind.VEHICLE_TAXONOMY: (
        HealthAction("Latih dan bandingkan kandidat", "/pengelolaan-model", primary=True),
        HealthAction("Lihat Armada", "/armada"),
    ),
}


def health_tasks(dashboard: MonitoringDashboard) -> list[HealthTask]:
    """The active alerts as things to do, most urgent first."""
    groups: dict[MonitoringAlertKind, list[MonitoringAlert]] = {}
    for alert in dashboard.active_alerts:
        groups.setdefault(alert.kind, []).append(alert)
    tasks = []
    for kind, members in groups.items():
        critical = any(a.severity is MonitoringAlertSeverity.CRITICAL for a in members)
        worst = MonitoringAlertSeverity.CRITICAL if critical else MonitoringAlertSeverity.WARNING
        tasks.append(
            HealthTask(
                kind=kind.value,
                title=_task_title(kind, len(members)),
                critical=critical,
                urgency=urgency_for(worst),
                findings=_findings(kind, members, dashboard),
                remediation=remediation_for(kind),
                actions=_ACTIONS.get(kind, ()),
            )
        )
    return sorted(tasks, key=lambda task: (not task.critical, task.title))


def _task_title(kind: MonitoringAlertKind, count: int) -> str:
    if kind is MonitoringAlertKind.MISSING_ACTUAL:
        return f"{count} operasi belum dicatat BBM aktualnya"
    if kind is MonitoringAlertKind.DATA_QUALITY:
        return f"{count} baris impor perlu diperbaiki"
    return alert_kind_label(kind)


def _findings(
    kind: MonitoringAlertKind, members: Sequence[MonitoringAlert], dashboard: MonitoringDashboard
) -> tuple[str, ...]:
    # One line per overdue operation or bad row would bury the action; those
    # are listed in full under the task instead.
    if kind is MonitoringAlertKind.MISSING_ACTUAL:
        return (
            f"Sudah lebih dari {dashboard.missing_actual_after_days} hari sejak diprediksi. "
            "Tanpa BBM aktual, ketepatan estimasinya tidak bisa diukur.",
        )
    if kind is MonitoringAlertKind.DATA_QUALITY:
        return ("Baris ini tidak ikut melatih model sampai diperbaiki dan diimpor ulang.",)
    return tuple(alert.message for alert in members)


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """A line of the all-clear list. Unmeasured checks say so rather than
    passing: "no drift" is a finding, "not enough data" is not."""

    text: str
    measured: bool = True


def health_checks(dashboard: MonitoringDashboard) -> list[HealthCheck]:
    """What is fine, for every kind with no active alert."""
    alerting = {alert.kind for alert in dashboard.active_alerts}
    checks: list[HealthCheck] = []
    if MonitoringAlertKind.MISSING_ACTUAL not in alerting:
        checks.append(
            HealthCheck(
                f"Tidak ada operasi yang lewat {dashboard.missing_actual_after_days} hari "
                "tanpa BBM aktual."
            )
        )
    if MonitoringAlertKind.MODEL_DEGRADATION not in alerting:
        if any(item.rolling_mae_liters is not None for item in dashboard.category_degradation):
            checks.append(HealthCheck("Estimasi masih dalam ambang ketepatan."))
        else:
            checks.append(
                HealthCheck("Ketepatan estimasi belum diukur: BBM aktual belum cukup.", False)
            )
    if MonitoringAlertKind.FEATURE_DRIFT not in alerting:
        if dashboard.feature_drift.status == "ready":
            checks.append(HealthCheck("Pola operasi masih sesuai data latih model."))
        else:
            checks.append(HealthCheck(_drift_not_measured(dashboard.feature_drift), False))
    if MonitoringAlertKind.DATA_QUALITY not in alerting:
        checks.append(HealthCheck("Tidak ada baris impor yang perlu diperbaiki."))
    return checks


def _drift_not_measured(drift: FeatureDriftSummary) -> str:
    """Why drift has no figure yet, naming the side that is short - it was
    "prediksi baru belum cukup" even when the training data was."""
    if drift.status == "no_active_model":
        return "Pergeseran data belum dihitung: belum ada model aktif."
    need = drift.minimum_row_count
    short = [
        f"{count} operasi {side}"
        for side, count in (
            ("data latih", drift.reference_row_count),
            ("terkini", drift.current_row_count),
        )
        if count < need
    ]
    if not short:
        return "Pergeseran data belum dihitung."
    each = "masing-masing perlu" if len(short) > 1 else "perlu"
    return f"Pergeseran data belum dihitung: baru {' dan '.join(short)}, {each} {need}."


# Plot geometry for the rolling-error line: a fixed viewBox the CSS scales,
# with room on the left for the value labels and below for the dates.
_CHART_WIDTH = 640
_CHART_HEIGHT = 200
_PAD_LEFT, _PAD_RIGHT, _PAD_TOP, _PAD_BOTTOM = 48, 16, 12, 28
# Where the top value sits, and how far apart two gutter ticks must be.
_TOP_TICK_Y, _TICK_GAP = 16, 14


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

    ys = [y_of(point.mae_liters) for point in points]

    threshold_y = y_of(threshold_liters)

    def value_y(index: int) -> float:
        """Where the first or last value's label sits: above its point unless
        the line or the threshold would run through the number there, then
        below. The label reaches about 30 units inward from the point."""
        here = ys[index]
        above, below = here - 10, min(here + 18, y_of(0) - 4)
        if len(ys) == 1:
            return above
        neighbour = ys[1] if index == 0 else ys[-2]
        line_under_label = here + (neighbour - here) * min(1.0, 30 / step)
        for baseline in (above, below):
            top, bottom = baseline - 11, baseline + 2
            if not (top <= line_under_label <= bottom or top - 2 <= threshold_y <= bottom + 2):
                return baseline
        return above

    plotted = [
        {
            "x": round(_PAD_LEFT + index * step, 1) if step else _PAD_LEFT + plot_width / 2,
            "y": ys[index],
            "value_y": value_y(index) if index in (0, len(points) - 1) else ys[index],
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
        "threshold_y": threshold_y,
        # A tick in the left gutter like 0 L and the top: a label on the line
        # itself sat on the latest point and its value. Left out where it
        # would crowd those two; the page says the threshold in words too.
        "threshold_tick": (
            f"{format_decimal(threshold_liters)} L"
            if y_of(0) - y_of(threshold_liters) >= _TICK_GAP
            and y_of(threshold_liters) - _TOP_TICK_Y >= _TICK_GAP
            else None
        ),
        "top_label": f"{format_decimal(round(top, 1))} L",
        "top_tick_y": _TOP_TICK_Y,
        "first_date": format_datetime(points[0].observed_at)[:10],
        "last_date": format_datetime(points[-1].observed_at)[:10],
        "left": _PAD_LEFT,
        "right": _CHART_WIDTH - _PAD_RIGHT,
        "bottom": _CHART_HEIGHT - _PAD_BOTTOM,
        "above_threshold": points[-1].mae_liters > threshold_liters,
    }
