"""Create-operation and prediction pages, on the Jinja design system (ADR 0007).

First page migrated off the f-string builders in ``form.py``; see
docs/production/implementation-progress.md for the migration order and status.
"""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import ValidationError

from fuel_predictor.application.baseline_predictions import (
    BaselineModelNotFoundError,
    GenerateFuelPrediction,
)
from fuel_predictor.application.daily_operations import CreateDailyOperation
from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.application.locations import LocationCatalog, LocationOption
from fuel_predictor.application.routing import RoutePreviewProvider, RoutingProviderUnavailable
from fuel_predictor.application.vehicles import VehicleCatalog
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
    location_catalog: LocationCatalog,
    vehicle_catalog: VehicleCatalog,
    route_preview: RoutePreviewProvider | None = None,
) -> APIRouter:
    router = APIRouter()

    def _vehicle_options() -> list[tuple[str, str]]:
        """Grouped in the label so a planner picking from twenty-odd units can
        see at a glance which kind of machine each one is."""
        return [
            (option.name, f"{option.name} — {option.group}" if option.group else option.name)
            for option in vehicle_catalog.options()
        ]

    def _resolved_stops(names: list[str]) -> tuple[str, ...]:
        """Only catalogued stops reach the provider, so the page cannot ask it for
        anything the planner could not have picked."""
        resolved = [location_catalog.find(name) for name in names]
        if len(resolved) < 2 or any(match is None for match in resolved):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Pemberhentian tidak dikenal."
            )
        return tuple(match.name for match in resolved if match is not None)

    @router.get("/prediksi", response_class=HTMLResponse)
    def show_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(
            _render_form(
                caller,
                {},
                [],
                location_catalog.options(),
                _vehicle_options(),
                route_preview is not None,
            )
        )

    @router.get("/prediksi/rute")
    def route_distance(request: Request, lokasi: Annotated[list[str], Query()]) -> JSONResponse:
        guard.require_caller(request)
        if route_preview is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Penyedia rute tidak tersedia.",
            )
        try:
            preview = route_preview.preview_route(_resolved_stops(lokasi))
        except RoutingProviderUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error
        return JSONResponse({"jarak_km": round(preview.total_distance_km, 1)})

    @router.post("/operasi-harian", response_class=HTMLResponse)
    async def submit_form(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        form_data = await request.form()
        submitted: dict[str, Any] = {
            key: str(value) for key, value in form_data.items() if key != "csrf_token"
        }
        # A row the planner left empty is not a stop, so it never reaches the
        # route: the sequence is the locations actually chosen, in order.
        submitted["stop_sequence"] = [
            stop
            for stop in (str(value).strip() for value in form_data.getlist("stop_sequence"))
            if stop
        ]
        payload: dict[str, Any] = dict(submitted)
        if payload.get("lifting_hours") == "":
            payload["lifting_hours"] = None
        if payload.get("vehicle") == "":
            payload["vehicle"] = None
        if payload.get("total_distance_km") == "":
            payload["total_distance_km"] = None

        try:
            validated = CreateDailyOperationRequest.model_validate(payload)
            operation = execute_create(validated, create_daily_operation)
        except ValidationError as error:
            return HTMLResponse(
                _render_form(
                    caller,
                    submitted,
                    translate_validation_errors(error.errors()),
                    location_catalog.options(),
                    _vehicle_options(),
                    route_preview is not None,
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except DailyOperationValidationError as error:
            return HTMLResponse(
                _render_form(
                    caller,
                    submitted,
                    [{"field": error.field, "message": error.message}],
                    location_catalog.options(),
                    _vehicle_options(),
                    route_preview is not None,
                ),
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
    caller: ActiveCaller,
    values: dict[str, Any],
    errors: list[dict[str, str]],
    location_options: tuple[LocationOption, ...],
    vehicle_options: list[tuple[str, str]],
    route_preview_available: bool = False,
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
        vehicle_options=vehicle_options,
        location_options=location_options,
        route_preview_available=route_preview_available,
    )
