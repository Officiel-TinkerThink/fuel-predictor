"""Bulk-prediction upload page, on the Jinja design system (ADR 0007)."""

import csv
from io import StringIO
from pathlib import PurePath
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from fuel_predictor.application.baseline_predictions import BaselineModelNotFoundError
from fuel_predictor.application.bulk_operation_predictions import (
    BulkOperationPrediction,
    BulkOperationPredictionResult,
)
from fuel_predictor.application.historical_datasets import HistoricalDatasetImportError
from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.delivery.events import ImportantEvents
from fuel_predictor.delivery.recent_results import RecentResults, result_gone
from fuel_predictor.delivery.rendering import ACTIVITY_LABELS, render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.delivery.uploads import read_sheet
from fuel_predictor.infrastructure.bulk_prediction_template import (
    BULK_PREDICTION_TEMPLATE_HEADERS,
)

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)

_PAGE_LEAD = (
    "Buat estimasi untuk banyak operasi sekaligus dari satu berkas. Baris yang bermasalah "
    "disisihkan beserta alasannya; baris lainnya tetap diproses."
)


def build_bulk_prediction_pages_router(
    bulk_operation_prediction: BulkOperationPrediction,
    guard: SecurityGuard,
    *,
    events: ImportantEvents,
    vehicle_catalog: VehicleCatalog | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/prediksi-operasi-massal", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_form(guard.require_caller(request), None))

    uploads: RecentResults[BulkOperationPredictionResult] = RecentResults()

    @router.post("/prediksi-operasi-massal", response_class=HTMLResponse)
    async def submit_form(request: Request, file: UploadFile = _UPLOAD_FILE) -> Response:
        caller = guard.require_caller(request)
        filename = file.filename or "berkas-prediksi-operasi"
        content = await read_sheet(file)
        digest = uploads.digest(content)
        # The same file again, moments later, is a refresh or a double tap:
        # every row would be planned twice. It leads to the result it has.
        earlier = uploads.same_file(caller.user.username, digest)
        if earlier is not None:
            return _to_result(earlier.token, repeated=True)
        try:
            result = bulk_operation_prediction.execute(
                filename, content, actor=caller.user.username
            )
            events.bulk_prediction_imported(caller.user.username, filename, result)
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
        kept = uploads.keep(caller.user.username, digest, filename, result)
        return _to_result(kept.token, repeated=False)

    @router.get("/prediksi-operasi-massal/hasil/{token}", response_class=HTMLResponse)
    def show_result(token: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        kept = uploads.get(token, caller.user.username)
        if kept is None:
            return result_gone(
                caller,
                "/prediksi-operasi-massal",
                "Prediksi Massal",
                "operasi yang dibuat ada di Riwayat Prediksi.",
            )
        result = kept.result
        return HTMLResponse(
            render(
                "prediksi-massal-selesai.html",
                caller=caller,
                page_title="Prediksi Operasi Massal Selesai",
                active_path="/prediksi-operasi-massal",
                result=result,
                repeated_at=kept.kept_at if request.query_params.get("ulang") == "1" else None,
                results_csv=_results_csv(result),
                results_filename=_results_filename(kept.filename),
                corrections_csv=_corrections_csv(result),
                corrections_filename=_results_filename(kept.filename).replace(
                    "hasil-prediksi-", "perbaiki-"
                ),
                accepted_count=len(result.accepted_rows),
                quarantined_count=len(result.correction_report),
                # Each accepted operation's catalog unit, so the printed slips
                # can say what each part of their codes stands for.
                vehicles={
                    row.operation.operation_id: vehicle_catalog.find(row.operation.vehicle)
                    for row in result.accepted_rows
                    if vehicle_catalog is not None and row.operation.vehicle
                },
            )
        )

    def _to_result(token: str, *, repeated: bool) -> RedirectResponse:
        suffix = "?ulang=1" if repeated else ""
        return RedirectResponse(
            f"/prediksi-operasi-massal/hasil/{token}{suffix}",
            status_code=status.HTTP_303_SEE_OTHER,
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


_RESULT_HEADERS = (
    "Baris sumber",
    "Kode operasi",
    "ID operasi",
    "Kendaraan",
    "Aktivitas",
    "Jam lifting",
    "Jarak total (km)",
    "Urutan pemberhentian",
    "Estimasi kebutuhan BBM (L)",
    "Alokasi rekomendasi (L)",
    "Rentang bawah (L)",
    "Rentang atas (L)",
    "Kode model",
    "Model",
)


def _results_csv(result: BulkOperationPredictionResult) -> str:
    """The accepted rows with their estimates, one line per source row, so the
    sheet the planner uploaded can come back with the numbers filled in. Built
    into the page as a data: link: nothing is stored for a second request."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(_RESULT_HEADERS)
    for row in result.accepted_rows:
        operation, prediction = row.operation, row.prediction
        writer.writerow(
            (
                f"{row.source.sheet_name} {row.source.row_number}",
                operation.operation_code or "",
                operation.operation_id,
                operation.vehicle or "",
                ACTIVITY_LABELS[operation.activity_mode.value],
                "" if operation.lifting_hours is None else operation.lifting_hours,
                operation.total_distance_km,
                " > ".join(operation.stop_sequence),
                prediction.estimated_fuel_requirement_liters,
                prediction.recommended_allocation_liters,
                prediction.uncertainty_lower_liters,
                prediction.uncertainty_upper_liters,
                prediction.model.model_code or "",
                prediction.model.model_version_id,
            )
        )
    return output.getvalue()


# The template's columns, in its order, and the field each one carries.
_TEMPLATE_FIELDS = (
    "vehicle",
    "activity_mode",
    "total_distance_km",
    "lifting_hours",
    "stop_sequence",
)


def _corrections_csv(result: BulkOperationPredictionResult) -> str:
    """Only the rows that need fixing, as typed, in the template's columns
    and with the problem beside them. Fixed and uploaded on their own they
    add just those operations; uploading the whole original file again would
    create every accepted operation a second time."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow((*BULK_PREDICTION_TEMPLATE_HEADERS, "Masalah"))
    for issue in result.correction_report:
        headers = issue.source.original_headers
        values = issue.source.raw_values
        writer.writerow(
            (
                *(
                    ""
                    if field not in headers or values.get(headers[field]) is None
                    else values[headers[field]]
                    for field in _TEMPLATE_FIELDS
                ),
                "; ".join(reason.message for reason in issue.reasons),
            )
        )
    return output.getvalue()


def _results_filename(uploaded: str | None) -> str:
    stem = PurePath(uploaded or "rencana-operasi").stem or "rencana-operasi"
    return f"hasil-prediksi-{stem}.csv"
