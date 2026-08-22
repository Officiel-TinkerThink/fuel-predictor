"""Monitoring pages, split into the plan's three views (ADR 0007, self-service-production-plan.md).

Kesehatan Sistem, Pergeseran Data, and Kinerja Model replace the single
combined `/pemantauan-operasi` page. Kinerja Model also absorbs the old
`/kinerja-prediksi` full-history performance report, since the plan's nav
only names one "Kinerja Model" item and the two features serve the same
question (is the model performing well) at different time horizons.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.actual_fuel import GetPredictionPerformance
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard


def build_monitoring_pages_router(
    get_monitoring_dashboard: GetMonitoringDashboard,
    get_prediction_performance: GetPredictionPerformance,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

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
                unresolved_data_quality_issue_count=dashboard.unresolved_data_quality_issue_count,
                unresolved_data_quality_issues=dashboard.unresolved_data_quality_issues,
                dataset_validation_summaries=dashboard.dataset_validation_summaries,
                missing_actual_predictions=dashboard.missing_actual_predictions,
                missing_actual_prediction_count=dashboard.missing_actual_prediction_count,
                missing_actual_after_days=dashboard.missing_actual_after_days,
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
                rolling_error_window=dashboard.rolling_error_window,
                category_degradation=dashboard.category_degradation,
                degradation_mae_threshold_liters=dashboard.degradation_mae_threshold_liters,
            )
        )

    return router
