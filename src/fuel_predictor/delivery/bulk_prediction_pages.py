"""Bulk-prediction upload page, on the Jinja design system (ADR 0007)."""

from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse

from fuel_predictor.application.baseline_predictions import BaselineModelNotFoundError
from fuel_predictor.application.bulk_operation_predictions import BulkOperationPrediction
from fuel_predictor.application.historical_datasets import HistoricalDatasetImportError
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)

_PAGE_LEAD = (
    "Unggah rencana operasi CSV atau Excel .xlsx. Baris yang valid tetap diprediksi, "
    "sementara baris lain dikarantina bersama alasan koreksinya."
)


def build_bulk_prediction_pages_router(
    bulk_operation_prediction: BulkOperationPrediction,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/prediksi-operasi-massal", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_form(guard.require_caller(request), None))

    @router.post("/prediksi-operasi-massal", response_class=HTMLResponse)
    async def submit_form(request: Request, file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            result = bulk_operation_prediction.execute(
                file.filename or "berkas-prediksi-operasi", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_form(caller, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except BaselineModelNotFoundError:
            return HTMLResponse(
                _render_form(
                    caller,
                    "Latih kandidat baseline dari dataset tervalidasi sebelum membuat "
                    "prediksi massal.",
                ),
                status_code=status.HTTP_409_CONFLICT,
            )

        return HTMLResponse(
            render(
                "prediksi-massal-selesai.html",
                caller=caller,
                page_title="Prediksi Operasi Massal Selesai",
                active_path="/prediksi-operasi-massal",
                eyebrow="PREDIKSI MASSAL SELESAI",
                page_lead="Rencana operasi sudah diproses.",
                result=result,
                accepted_count=len(result.accepted_rows),
                quarantined_count=len(result.correction_report),
                ignored_count=result.ignored_blank_row_count,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    return router


def _render_form(caller: "ActiveCaller", error: str | None) -> str:
    return render(
        "prediksi-massal.html",
        caller=caller,
        page_title="Prediksi Operasi Massal",
        active_path="/prediksi-operasi-massal",
        eyebrow="PERENCANAAN BAHAN BAKAR",
        page_lead=_PAGE_LEAD,
        error=error,
    )
