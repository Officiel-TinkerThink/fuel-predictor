"""Historical dataset import and baseline training pages (ADR 0007)."""

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from fuel_predictor.application.baseline_predictions import (
    BaselineTrainingError,
    TrainBaselineCandidate,
)
from fuel_predictor.application.historical_datasets import (
    DatasetVersionNotFoundError,
    HistoricalDatasetImportError,
    HistoricalDatasetImportResult,
    ImportHistoricalDataset,
)
from fuel_predictor.delivery.events import ImportantEvents
from fuel_predictor.delivery.recent_results import RecentResults, result_gone
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.delivery.uploads import read_sheet

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)
# Package data, for the same reason as the model-package schemas: resolving
# this by walking up from __file__ works only from a source checkout.
_DEMO_HISTORICAL_DATA = Path(
    str(resources.files("fuel_predictor") / "examples" / "riwayat-angber-demo.csv")
)

_PAGE_LEAD = (
    "Riwayat operasi beserta BBM yang disiapkan, untuk melatih kandidat model. Baris yang "
    "bermasalah disisihkan beserta alasannya; baris lainnya tetap diimpor."
)


def build_historical_dataset_pages_router(
    import_historical_dataset: ImportHistoricalDataset,
    train_baseline_candidate: TrainBaselineCandidate,
    guard: SecurityGuard,
    *,
    events: ImportantEvents,
) -> APIRouter:
    router = APIRouter()

    @router.get("/impor-data-historis", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_form(guard.require_caller(request), None))

    @router.get("/contoh-data-riwayat.csv")
    def download_demo_historical_data() -> Response:
        return Response(
            content=_DEMO_HISTORICAL_DATA.read_bytes(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="riwayat-angber-demo.csv"'},
        )

    uploads: RecentResults[HistoricalDatasetImportResult] = RecentResults()

    @router.post("/impor-data-historis", response_class=HTMLResponse)
    async def submit_import(request: Request, file: UploadFile = _UPLOAD_FILE) -> Response:
        caller = guard.require_caller(request)
        filename = file.filename or "berkas-impor"
        content = await read_sheet(file)
        digest = uploads.digest(content)
        # The same history again, moments later, is a refresh or a double
        # tap: it would become a second, identical dataset version.
        earlier = uploads.same_file(caller.user.username, digest)
        if earlier is not None:
            return _to_import_result(earlier.token, repeated=True)
        try:
            result = import_historical_dataset.execute(filename, content)
            events.historical_dataset_imported(caller.user.username, result.dataset_version)
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_form(caller, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        kept = uploads.keep(caller.user.username, digest, filename, result)
        return _to_import_result(kept.token, repeated=False)

    @router.get("/impor-data-historis/hasil/{token}", response_class=HTMLResponse)
    def show_import_result(token: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        kept = uploads.get(token, caller.user.username)
        if kept is None:
            return result_gone(
                caller,
                "/impor-data-historis",
                "Impor Data Historis",
                "versi dataset yang dibuat ada di Pengelolaan Model.",
            )
        return HTMLResponse(
            render(
                "impor-data-historis-selesai.html",
                caller=caller,
                page_title="Dataset historis berhasil diimpor",
                active_path="/impor-data-historis",
                eyebrow="DATASET TERVERIFIKASI",
                dataset=kept.result.dataset_version,
                result=kept.result,
                repeated_at=kept.kept_at if request.query_params.get("ulang") == "1" else None,
            )
        )

    def _to_import_result(token: str, *, repeated: bool) -> RedirectResponse:
        suffix = "?ulang=1" if repeated else ""
        return RedirectResponse(
            f"/impor-data-historis/hasil/{token}{suffix}", status_code=status.HTTP_303_SEE_OTHER
        )

    @router.post(
        "/dataset-versions/{dataset_version_id}/latih-kandidat-baseline",
        response_class=HTMLResponse,
    )
    def train_baseline(dataset_version_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            model = train_baseline_candidate.execute(dataset_version_id)
            events.model_candidate_trained(caller.user.username, model)
        except (BaselineTrainingError, DatasetVersionNotFoundError) as error:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Kandidat baseline belum dapat dilatih",
                    active_path="/impor-data-historis",
                    message=str(error),
                    detail=f"ID versi dataset: {dataset_version_id}",
                    back_href="/impor-data-historis",
                    back_label="Kembali ke impor data",
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        # Where the next step is - comparing and promoting - and where a
        # refresh reloads a page rather than training a second candidate.
        return RedirectResponse(
            f"/pengelolaan-model?dilatih={model.model_version_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return router


def _render_form(caller: "ActiveCaller", error: str | None) -> str:
    return render(
        "impor-data-historis.html",
        caller=caller,
        page_title="Impor Data Historis",
        active_path="/impor-data-historis",
        eyebrow="DATA PELATIHAN",
        page_lead=_PAGE_LEAD,
        error=error,
    )
