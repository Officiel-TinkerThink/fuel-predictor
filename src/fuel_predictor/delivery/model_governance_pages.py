"""Model governance and candidate comparison pages (ADR 0007)."""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse

from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.application.model_lifecycle import (
    CandidateModelNotFoundError,
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    ModelPromotionNotAllowedError,
    PromoteCandidateModel,
)
from fuel_predictor.application.retained_package_activation import (
    ActivateRetainedModelPackage,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.model_activation import (
    ModelActivationError,
    PostActivationHealthCheckFailedError,
)
from fuel_predictor.domain.model_package import ModelPackageValidationError


def build_model_governance_pages_router(
    promote_candidate_model: PromoteCandidateModel,
    activate_retained_package: ActivateRetainedModelPackage,
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

        # An ingested package has retained bytes, so activating it runs the
        # full ADR 0010 sequence: load, warm, smoke-test, persist under
        # optimistic concurrency, swap, health-check. A model trained in this
        # process has no package to load, so it keeps the simpler path.
        if activate_retained_package.can_activate(model_version_id):
            return _activate_package(model_version_id, caller)

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

    def _activate_package(model_version_id: str, caller: "ActiveCaller") -> HTMLResponse:
        try:
            result = activate_retained_package.execute(model_version_id)
        except PostActivationHealthCheckFailedError as error:
            # Reported loudly and never silently reverted: the swap already
            # happened, so pretending otherwise would hide which model is
            # actually serving.
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Model aktif tetapi pemeriksaan gagal",
                    active_path="/pengelolaan-model",
                    message=(
                        f"{error} Model ini sudah melayani prediksi. Periksa segera, dan "
                        "kembalikan ke versi sebelumnya bila perlu."
                    ),
                    back_href="/pengelolaan-model",
                    back_label="Kembali ke pengelolaan model",
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except ModelPackageValidationError as error:
            # The retained bytes no longer match the manifest they were
            # accepted under. Nothing was loaded, so the previous model is
            # untouched; the operator needs the specific member named.
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Paket model tidak lagi utuh",
                    active_path="/pengelolaan-model",
                    message=(
                        "Berkas paket yang tersimpan tidak cocok dengan manifesnya: "
                        + "; ".join(f"{field}: {message}" for field, message in error.errors)
                        + ". Unggah ulang paket tersebut sebelum mengaktifkannya."
                    ),
                    back_href="/pengelolaan-model",
                    back_label="Kembali ke pengelolaan model",
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        except ModelActivationError as error:
            # Everything before the swap leaves the previous model both active
            # and loaded, so this is a safe failure to report plainly.
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Aktivasi model gagal",
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
                page_title="Model diaktifkan",
                active_path="/pengelolaan-model",
                eyebrow="AKTIVASI PAKET SELESAI",
                model=result.activated,
            ),
            status_code=status.HTTP_200_OK,
        )

    return router
