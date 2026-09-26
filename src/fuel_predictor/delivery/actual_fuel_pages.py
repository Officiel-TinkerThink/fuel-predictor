"""Actual-fuel recording pages (single + bulk), on the Jinja design system (ADR 0007)."""

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    ListOperationsAwaitingActualFuel,
    OperationAwaitingActualFuel,
    RecordActualFuel,
    RecordActualFuelCommand,
)
from fuel_predictor.application.bulk_actual_fuel import BulkActualFuel, BulkActualFuelResult
from fuel_predictor.application.daily_operations import (
    DailyOperationNotFoundError,
    OperationCancelledError,
)
from fuel_predictor.application.historical_datasets import HistoricalDatasetImportError
from fuel_predictor.delivery.events import ImportantEvents
from fuel_predictor.delivery.http import ActualFuelRequest, translate_validation_errors
from fuel_predictor.delivery.recent_results import RecentResults, result_gone
from fuel_predictor.delivery.rendering import format_decimal, render, site_time
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.delivery.uploads import read_sheet
from fuel_predictor.domain.daily_operation import DailyOperationValidationError
from fuel_predictor.infrastructure.actual_fuel_template import waiting_xlsx

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)
_NO_CODE = "Kode operasi wajib diisi."


def build_actual_fuel_pages_router(
    record_actual_fuel: RecordActualFuel,
    bulk_actual_fuel: BulkActualFuel,
    list_awaiting_actual: ListOperationsAwaitingActualFuel,
    guard: SecurityGuard,
    *,
    events: ImportantEvents,
) -> APIRouter:
    router = APIRouter()

    def _form(caller: "ActiveCaller", values: dict[str, Any], errors: list[dict[str, str]]) -> str:
        return _render_form(caller, values, errors, list_awaiting_actual.execute())

    @router.get("/bahan-bakar-aktual", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        # A "Catat" link from the waiting list lands here with the id filled
        # in, so the person only has to type the litres.
        chosen = request.query_params.get("operation_id", "").strip()
        values = {"operation_id": chosen} if chosen else {}
        return HTMLResponse(_form(guard.require_caller(request), values, []))

    @router.get("/bahan-bakar-aktual/menunggu.xlsx")
    def download_waiting(request: Request) -> Response:
        """The waiting operations as a sheet to fill in and upload back."""
        guard.require_caller(request)
        rows = [
            (
                item.operation_code or item.operation_id,
                item.vehicle or item.vehicle_category.value,
                site_time(item.predicted_at),
                f"{item.departure} → {item.destination}" if item.departure else "",
                item.recommended_allocation_liters,
            )
            for item in list_awaiting_actual.execute()
        ]
        return Response(
            content=waiting_xlsx(rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="bbm-aktual-menunggu.xlsx"'},
        )

    @router.post("/bahan-bakar-aktual", response_class=HTMLResponse)
    async def submit_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        form_data = await request.form()
        submitted = {key: str(value) for key, value in form_data.items() if key != "csrf_token"}
        # How the day was planned, to say how the figure landed: read before
        # recording, while the operation is still among those waiting.
        waiting = {item.operation_id: item for item in list_awaiting_actual.execute()}
        reference = submitted.get("operation_id", "").strip()
        # Every problem with the form is named at once: a blank code is not an
        # unknown one, and it is said alongside whatever is wrong with the litres.
        problems = [] if reference else [{"field": "operation_id", "message": _NO_CODE}]
        payload = {key: value for key, value in submitted.items() if key != "operation_id"}
        try:
            validated = ActualFuelRequest.model_validate(payload)
        except ValidationError as error:
            problems += translate_validation_errors(error.errors())
        if problems:
            return HTMLResponse(
                _form(caller, submitted, problems),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        try:
            record = record_actual_fuel.execute(
                RecordActualFuelCommand(
                    operation_reference=reference,
                    actual_fuel_liters=validated.actual_fuel_liters,
                    measurement_source=validated.measurement_source,
                    recorded_by=caller.user.username,
                )
            )
            events.actual_fuel_recorded(
                caller.user.username, record, record_actual_fuel.code_for(record)
            )
        except DailyOperationValidationError as error:
            return HTMLResponse(
                _form(caller, submitted, [{"field": error.field, "message": error.message}]),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except OperationCancelledError:
            return HTMLResponse(
                _form(
                    caller,
                    submitted,
                    [
                        {
                            "field": "operation_id",
                            "message": "Operasi ini sudah dibatalkan; BBM aktualnya tidak dicatat.",
                        }
                    ],
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        except ActualFuelAlreadyRecordedError as error:
            return HTMLResponse(
                _form(
                    caller,
                    submitted,
                    [{"field": "operation_id", "message": _already_recorded(error, validated)}],
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        except DailyOperationNotFoundError:
            return HTMLResponse(
                _form(
                    caller,
                    submitted,
                    [
                        {
                            "field": "operation_id",
                            "message": (
                                "Kode operasi tidak ditemukan. Periksa lagi kode yang "
                                "dicatat saat estimasi dibuat."
                            ),
                        }
                    ],
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return HTMLResponse(
            render(
                "bbm-aktual-tersimpan.html",
                caller=caller,
                page_title="Bahan Bakar Aktual Tersimpan",
                active_path="/bahan-bakar-aktual",
                record=record,
                operation_code=record_actual_fuel.code_for(record),
                planned=waiting.get(record.operation_id),
                still_waiting=len(waiting) - (record.operation_id in waiting),
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.get("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    def show_bulk_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_bulk_form(guard.require_caller(request), None))

    uploads: RecentResults[BulkActualFuelResult] = RecentResults()

    @router.post("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    async def submit_bulk_form(request: Request, file: UploadFile = _UPLOAD_FILE) -> Response:
        caller = guard.require_caller(request)
        filename = file.filename or "berkas-bbm-aktual"
        content = await read_sheet(file)
        digest = uploads.digest(content)
        # The same bytes again, moments later, is a refresh or a double tap;
        # it leads to the result already made rather than a page of
        # "sudah tercatat" for every row.
        earlier = uploads.same_file(caller.user.username, digest)
        if earlier is not None:
            return _to_bulk_result(earlier.token, repeated=True)
        try:
            result = bulk_actual_fuel.execute(filename, content, actor=caller.user.username)
            events.bulk_actual_imported(caller.user.username, filename, result)
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_bulk_form(caller, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        kept = uploads.keep(caller.user.username, digest, filename, result)
        return _to_bulk_result(kept.token, repeated=False)

    @router.get("/bahan-bakar-aktual-massal/hasil/{token}", response_class=HTMLResponse)
    def show_bulk_result(token: str, request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        kept = uploads.get(token, caller.user.username)
        if kept is None:
            return result_gone(
                caller,
                "/bahan-bakar-aktual-massal",
                "Impor Massal",
                "BBM aktual yang dicatat ada di Riwayat Prediksi.",
            )
        result = kept.result
        return HTMLResponse(
            render(
                "bbm-aktual-massal-selesai.html",
                caller=caller,
                page_title="Impor Bahan Bakar Aktual Selesai",
                active_path="/bahan-bakar-aktual-massal",
                result=result,
                repeated_at=kept.kept_at if request.query_params.get("ulang") == "1" else None,
                accepted_count=len(result.accepted_rows),
                quarantined_count=len(result.correction_report),
                unfilled_count=result.unfilled_row_count,
                already_count=result.already_recorded_row_count,
            )
        )

    def _to_bulk_result(token: str, *, repeated: bool) -> RedirectResponse:
        suffix = "?ulang=1" if repeated else ""
        return RedirectResponse(
            f"/bahan-bakar-aktual-massal/hasil/{token}{suffix}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return router


def _render_form(
    caller: "ActiveCaller",
    values: dict[str, Any],
    errors: list[dict[str, str]],
    awaiting: tuple[OperationAwaitingActualFuel, ...],
) -> str:
    return render(
        "bbm-aktual.html",
        caller=caller,
        page_title="Catat Bahan Bakar Aktual",
        active_path="/bahan-bakar-aktual",
        eyebrow="UMPAN BALIK OPERASI",
        page_lead="Masukkan BBM yang benar-benar terpakai untuk operasi yang sudah selesai.",
        values=values,
        errors=errors,
        awaiting=awaiting,
    )


def _render_bulk_form(caller: "ActiveCaller", error: str | None) -> str:
    return render(
        "bbm-aktual-massal.html",
        caller=caller,
        page_title="Impor Bahan Bakar Aktual",
        active_path="/bahan-bakar-aktual-massal",
        eyebrow="UMPAN BALIK OPERASI",
        page_lead=(
            "Isi BBM aktual banyak operasi sekaligus dari satu berkas. Baris yang bermasalah "
            "disisihkan beserta alasannya; baris lainnya tetap disimpan."
        ),
        error=error,
    )


def _already_recorded(error: ActualFuelAlreadyRecordedError, request: ActualFuelRequest) -> str:
    """Says the figure on record, so a person can tell a repeat from a mistake."""
    if error.recorded_liters is None:
        return "Bahan bakar aktual untuk operasi ini sudah tercatat."
    recorded = format_decimal(error.recorded_liters)
    if error.repeats(request.actual_fuel_liters):
        return f"Sudah tercatat dengan angka yang sama ({recorded} L); tidak perlu dicatat lagi."
    return (
        f"Operasi ini sudah tercatat {recorded} L. Angka yang sudah tercatat tidak diubah di sini."
    )
