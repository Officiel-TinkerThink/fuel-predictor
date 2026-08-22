"""Historical dataset import and baseline training pages (ADR 0007)."""

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response

from fuel_predictor.application.baseline_predictions import (
    BaselineTrainingError,
    TrainBaselineCandidate,
)
from fuel_predictor.application.historical_datasets import (
    DatasetVersionNotFoundError,
    HistoricalDatasetImportError,
    ImportHistoricalDataset,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)
_DEMO_HISTORICAL_DATA = Path(__file__).resolve().parents[3] / "examples" / "riwayat-angber-demo.csv"

_PAGE_LEAD = (
    "Unggah CSV atau Excel .xlsx. Baris kosong kalender diabaikan; baris yang perlu diperbaiki "
    "akan dikarantina dalam laporan koreksi."
)


def build_historical_dataset_pages_router(
    import_historical_dataset: ImportHistoricalDataset,
    train_baseline_candidate: TrainBaselineCandidate,
    guard: SecurityGuard,
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

    @router.post("/impor-data-historis", response_class=HTMLResponse)
    async def submit_import(request: Request, file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            result = import_historical_dataset.execute(
                file.filename or "berkas-impor", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_form(caller, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return HTMLResponse(
            render(
                "impor-data-historis-selesai.html",
                caller=caller,
                page_title="Dataset historis berhasil diimpor",
                active_path="/impor-data-historis",
                eyebrow="DATASET TERVERIFIKASI",
                dataset=result.dataset_version,
                result=result,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.post(
        "/dataset-versions/{dataset_version_id}/latih-kandidat-baseline",
        response_class=HTMLResponse,
    )
    def train_baseline(dataset_version_id: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            model = train_baseline_candidate.execute(dataset_version_id)
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
        return HTMLResponse(
            render(
                "kandidat-terlatih.html",
                caller=caller,
                page_title="Kandidat baseline siap digunakan",
                active_path="/impor-data-historis",
                eyebrow="KANDIDAT DILATIH MANUAL",
                model=model,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    return router


def _render_form(caller: "ActiveCaller", error: str | None) -> str:
    return render(
        "impor-data-historis.html",
        caller=caller,
        page_title="Impor Data Historis ANGBER",
        active_path="/impor-data-historis",
        eyebrow="DATA PELATIHAN",
        page_lead=_PAGE_LEAD,
        error=error,
    )
