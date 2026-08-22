"""Model governance and candidate comparison pages (ADR 0007)."""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse

from fuel_predictor.application.model_lifecycle import (
    CandidateModelNotFoundError,
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    ModelPromotionNotAllowedError,
    PromoteCandidateModel,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard


def build_model_governance_pages_router(
    promote_candidate_model: PromoteCandidateModel,
    get_candidate_model_comparison: GetCandidateModelComparison,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/pengelolaan-model", response_class=HTMLResponse)
    def show_governance(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(
            render(
                "pengelolaan-model.html",
                caller=caller,
                page_title="Pengelolaan Model",
                active_path="/pengelolaan-model",
                eyebrow="TATA KELOLA MODEL",
                dashboard=get_model_governance_dashboard.execute(),
            )
        )

    @router.get("/kandidat-model/{model_version_id}/perbandingan", response_class=HTMLResponse)
    def show_comparison(model_version_id: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            comparison = get_candidate_model_comparison.execute(model_version_id)
        except CandidateModelNotFoundError:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Kandidat model tidak ditemukan",
                    active_path="/pengelolaan-model",
                    message="Pilih kandidat yang masih menunggu tinjauan.",
                    back_href="/pengelolaan-model",
                    back_label="Kembali ke pengelolaan model",
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(
            render(
                "kandidat-perbandingan.html",
                caller=caller,
                page_title="Perbandingan Kandidat Model",
                active_path="/pengelolaan-model",
                eyebrow="PERBANDINGAN MANUAL",
                comparison=comparison,
            )
        )

    @router.post("/kandidat-model/{model_version_id}/promosikan", response_class=HTMLResponse)
    def promote_candidate(model_version_id: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            model = promote_candidate_model.execute(model_version_id)
        except CandidateModelNotFoundError:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Kandidat model tidak ditemukan",
                    active_path="/pengelolaan-model",
                    message="Kandidat model tidak ditemukan atau bukan lagi kandidat.",
                    back_href="/pengelolaan-model",
                    back_label="Kembali ke pengelolaan model",
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except ModelPromotionNotAllowedError as error:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Promosi model tidak dapat dilakukan",
                    active_path="/pengelolaan-model",
                    message=str(error),
                    back_href="/pengelolaan-model",
                    back_label="Kembali ke pengelolaan model",
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        return HTMLResponse(
            render(
                "model-dipromosikan.html",
                caller=caller,
                page_title="Model dipromosikan",
                active_path="/pengelolaan-model",
                eyebrow="PROMOSI MANUAL SELESAI",
                model=model,
            ),
            status_code=status.HTTP_200_OK,
        )

    return router
