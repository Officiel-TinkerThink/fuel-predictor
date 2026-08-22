"""Create-operation and prediction pages, on the Jinja design system (ADR 0007).

First page migrated off the f-string builders in ``form.py``; see
docs/production/implementation-progress.md for the migration order and status.
"""

from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from fuel_predictor.application.baseline_predictions import (
    BaselineModelNotFoundError,
    GenerateFuelPrediction,
)
from fuel_predictor.application.daily_operations import CreateDailyOperation
from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.delivery.http import (
    CreateDailyOperationRequest,
    execute_create,
    translate_validation_errors,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.daily_operation import DailyOperationValidationError

_MODE_LABELS = {
    "transport": "Angkut",
    "lifting": "Lifting",
    "transport_and_lifting": "Angkut dan lifting",
}
_SOURCE_LABELS = {"manual": "Input manual", "routing_provider": "Penyedia rute"}


def build_prediction_pages_router(
    create_daily_operation: CreateDailyOperation,
    generate_fuel_prediction: GenerateFuelPrediction,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/prediksi", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(_render_form(caller, {}, []))

    @router.post("/operasi-harian", response_class=HTMLResponse)
    async def submit_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        form_data = await request.form()
        submitted: dict[str, Any] = {
            key: str(value) for key, value in form_data.items() if key != "csrf_token"
        }
        submitted["stop_sequence"] = [
            str(value).strip() for value in form_data.getlist("stop_sequence") if str(value).strip()
        ]
        payload: dict[str, Any] = dict(submitted)
        if payload.get("lifting_hours") == "":
            payload["lifting_hours"] = None

        try:
            validated = CreateDailyOperationRequest.model_validate(payload)
            operation = execute_create(validated, create_daily_operation)
        except ValidationError as error:
            return HTMLResponse(
                _render_form(caller, submitted, translate_validation_errors(error.errors())),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except DailyOperationValidationError as error:
            return HTMLResponse(
                _render_form(caller, submitted, [{"field": error.field, "message": error.message}]),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        return HTMLResponse(
            render(
                "operasi-tersimpan.html",
                caller=caller,
                page_title="Operasi harian tersimpan",
                active_path="/prediksi",
                operation=operation,
                mode_label=_MODE_LABELS[operation.activity_mode.value],
                source_label=_SOURCE_LABELS[operation.distance_source.value],
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.post("/operasi-harian/{operation_id}/prediksi", response_class=HTMLResponse)
    def submit_prediction(operation_id: str, request: Request) -> Response:
        caller = guard.require_caller(request)
        try:
            prediction = generate_fuel_prediction.execute(operation_id)
        except BaselineModelNotFoundError:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Prediksi belum tersedia",
                    active_path="/prediksi",
                    message=(
                        "Latih kandidat baseline dari dataset tervalidasi sebelum membuat "
                        "estimasi untuk operasi ini."
                    ),
                    back_href="/",
                    back_label="Kembali ke ringkasan",
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        return HTMLResponse(
            render(
                "estimasi.html",
                caller=caller,
                page_title="Estimasi kebutuhan bahan bakar",
                active_path="/prediksi",
                prediction=prediction,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    return router


def _render_form(
    caller: ActiveCaller, values: dict[str, Any], errors: list[dict[str, str]]
) -> str:
    return render(
        "prediksi.html",
        caller=caller,
        page_title="Buat Operasi Harian",
        active_path="/prediksi",
        eyebrow="PERENCANAAN BAHAN BAKAR",
        page_lead="Catat satu rencana operasi ANGBER secara lengkap dan konsisten.",
        values=values,
        errors=errors,
    )
