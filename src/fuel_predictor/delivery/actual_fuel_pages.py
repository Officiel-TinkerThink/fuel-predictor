"""Actual-fuel recording pages (single + bulk), on the Jinja design system (ADR 0007)."""

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    RecordActualFuel,
    RecordActualFuelCommand,
)
from fuel_predictor.application.bulk_actual_fuel import BulkActualFuel
from fuel_predictor.application.daily_operations import DailyOperationNotFoundError
from fuel_predictor.application.historical_datasets import HistoricalDatasetImportError
from fuel_predictor.delivery.http import ActualFuelRequest, translate_validation_errors
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.daily_operation import DailyOperationValidationError

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)


def build_actual_fuel_pages_router(
    record_actual_fuel: RecordActualFuel,
    bulk_actual_fuel: BulkActualFuel,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/bahan-bakar-aktual", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_form(guard.require_caller(request), {}, []))

    @router.post("/bahan-bakar-aktual", response_class=HTMLResponse)
    async def submit_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        form_data = await request.form()
        submitted = {
            key: str(value) for key, value in form_data.items() if key != "csrf_token"
        }
        try:
            payload = {key: value for key, value in submitted.items() if key != "operation_id"}
            validated = ActualFuelRequest.model_validate(payload)
            record = record_actual_fuel.execute(
                RecordActualFuelCommand(
                    operation_id=submitted.get("operation_id", "").strip(),
                    actual_fuel_liters=validated.actual_fuel_liters,
                    measurement_source=validated.measurement_source,
                )
            )
        except ValidationError as error:
            return HTMLResponse(
                _render_form(caller, submitted, translate_validation_errors(error.errors())),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except DailyOperationValidationError as error:
            return HTMLResponse(
                _render_form(
                    caller, submitted, [{"field": error.field, "message": error.message}]
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except ActualFuelAlreadyRecordedError:
            return HTMLResponse(
                _render_form(
                    caller,
                    submitted,
                    [
                        {
                            "field": "operation_id",
                            "message": "Bahan bakar aktual untuk operasi ini sudah tercatat.",
                        }
                    ],
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        except DailyOperationNotFoundError:
            return HTMLResponse(
                _render_form(
                    caller,
                    submitted,
                    [{"field": "operation_id", "message": "ID operasi tidak ditemukan."}],
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return HTMLResponse(
            render(
                "bbm-aktual-tersimpan.html",
                caller=caller,
                page_title="Bahan Bakar Aktual Tersimpan",
                active_path="/bahan-bakar-aktual",
                eyebrow="UMPAN BALIK TERSIMPAN",
                record=record,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.get("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    def show_bulk_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_bulk_form(guard.require_caller(request), None))

    @router.post("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    async def submit_bulk_form(request: Request, file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        caller = guard.require_caller(request)
        try:
            result = bulk_actual_fuel.execute(
                file.filename or "berkas-bbm-aktual", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_bulk_form(caller, error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        return HTMLResponse(
            render(
                "bbm-aktual-massal-selesai.html",
                caller=caller,
                page_title="Impor Bahan Bakar Aktual Selesai",
                active_path="/bahan-bakar-aktual-massal",
                eyebrow="IMPOR AKTUAL SELESAI",
                page_lead="Bahan bakar aktual sudah diproses.",
                result=result,
                accepted_count=len(result.accepted_rows),
                quarantined_count=len(result.correction_report),
                ignored_count=result.ignored_blank_row_count,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    return router


def _render_form(
    caller: "ActiveCaller", values: dict[str, Any], errors: list[dict[str, str]]
) -> str:
    return render(
        "bbm-aktual.html",
        caller=caller,
        page_title="Catat Bahan Bakar Aktual",
        active_path="/bahan-bakar-aktual",
        eyebrow="UMPAN BALIK OPERASI",
        page_lead=(
            "Masukkan konsumsi BBM setelah operasi selesai. Nilai ini disimpan terpisah "
            "dari bahan bakar disiapkan."
        ),
        values=values,
        errors=errors,
    )


def _render_bulk_form(caller: "ActiveCaller", error: str | None) -> str:
    return render(
        "bbm-aktual-massal.html",
        caller=caller,
        page_title="Impor Bahan Bakar Aktual",
        active_path="/bahan-bakar-aktual-massal",
        eyebrow="UMPAN BALIK OPERASI",
        page_lead=(
            "Unggah CSV atau Excel .xlsx. Baris valid tetap disimpan; ID tidak cocok dan "
            "nilai tidak valid dikarantina."
        ),
        error=error,
    )
