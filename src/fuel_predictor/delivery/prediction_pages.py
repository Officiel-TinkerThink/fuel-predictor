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
from fuel_predictor.application.catalog_resolution import UnknownLocationError, resolve_location
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    DailyOperationNotFoundError,
    GetDailyOperation,
)
from fuel_predictor.application.identity import ActiveCaller
from fuel_predictor.application.locations import LocationCatalog, LocationOption
from fuel_predictor.application.prediction_history import (
    GetLatestPrediction,
    ListRecentPredictions,
)
from fuel_predictor.application.routing import RoutePreviewProvider, RoutingProviderUnavailable
from fuel_predictor.application.similar_operations import (
    FindSimilarOperations,
    SimilarOperation,
    SimilarOperationsQuery,
    VehicleMatch,
)
from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.delivery.events import ImportantEvents
from fuel_predictor.delivery.http import (
    CreateDailyOperationRequest,
    execute_create,
    translate_validation_errors,
)
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.daily_operation import DailyOperation, DailyOperationValidationError
from fuel_predictor.domain.prediction import FuelPrediction

_HISTORY_MAX = 500
_MODE_LABELS = {
    "transport": "Angkut",
    "lifting": "Lifting",
    "transport_and_lifting": "Angkut dan lifting",
}
_SOURCE_LABELS = {"manual": "Input manual", "routing_provider": "Penyedia rute"}
# Why a past operation is shown, in the planner's words: the fallback order
# ADR 0015 fixes, same unit before same type before same group.
_MATCH_LABELS = {
    VehicleMatch.SAME: "Unit yang sama",
    VehicleMatch.SAME_TYPE: "Tipe yang sama",
    VehicleMatch.SAME_GROUP: "Grup yang sama",
}
# Enough to judge the number against, few enough to read at a glance.
_SIMILAR_LIMIT = 5


def build_prediction_pages_router(
    create_daily_operation: CreateDailyOperation,
    generate_fuel_prediction: GenerateFuelPrediction,
    get_daily_operation: GetDailyOperation,
    list_recent_predictions: ListRecentPredictions,
    get_latest_prediction: GetLatestPrediction,
    guard: SecurityGuard,
    location_catalog: LocationCatalog,
    vehicle_catalog: VehicleCatalog,
    route_preview: RoutePreviewProvider | None = None,
    find_similar_operations: FindSimilarOperations | None = None,
    *,
    events: ImportantEvents,
) -> APIRouter:
    router = APIRouter()

    def _vehicle_options() -> list[tuple[str, list[tuple[str, str]]]]:
        """Units under their kind of machine (Crane, Truck, …) in the order the
        catalogue lists them, so the picker reads as headed groups rather than
        twenty-odd suffixed names. Units with no group come last, unlabelled."""
        groups: dict[str, list[tuple[str, str]]] = {}
        for option in vehicle_catalog.options():
            groups.setdefault(option.group or "Lainnya", []).append((option.name, option.name))
        ordered = [(name, units) for name, units in groups.items() if name != "Lainnya"]
        if "Lainnya" in groups:
            ordered.append(("Lainnya", groups["Lainnya"]))
        return ordered

    def _resolved_stop_names(names: list[str]) -> list[str]:
        """A typed stop becomes the catalogue's own spelling, the same tolerant
        way an agent's request is matched. With no catalogue loaded there is
        nothing to match against, so the names pass through as written."""
        if not location_catalog.options():
            return names
        return [resolve_location(location_catalog, name).name for name in names]

    def _resolved_stops(names: list[str]) -> tuple[str, ...]:
        """Only catalogued stops reach the provider, so the page cannot ask it for
        anything the planner could not have picked."""
        resolved = [location_catalog.find(name) for name in names]
        if len(resolved) < 2 or any(match is None for match in resolved):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Pemberhentian tidak dikenal."
            )
        return tuple(match.name for match in resolved if match is not None)

    def _similar(operation: DailyOperation | None) -> tuple[SimilarOperation, ...]:
        """What the same unit - or the nearest kind of unit - needed on days
        like this one. The number is easier to trust next to them (ADR 0013).
        Without a named vehicle there is nothing to look them up by."""
        if find_similar_operations is None or operation is None or not operation.vehicle:
            return ()
        return find_similar_operations.execute(
            SimilarOperationsQuery(
                vehicle=operation.vehicle,
                vehicle_category=operation.vehicle_category,
                activity_mode=operation.activity_mode,
                lifting_hours=operation.lifting_hours,
                total_distance_km=operation.total_distance_km,
                limit=_SIMILAR_LIMIT,
                exclude_operation_id=operation.operation_id,
            )
        )

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
        try:
            payload["stop_sequence"] = _resolved_stop_names(submitted["stop_sequence"])
        except UnknownLocationError as error:
            return HTMLResponse(
                _render_form(
                    caller,
                    submitted,
                    [{"field": "stop_sequence", "message": _unknown_stop_message(error)}],
                    location_catalog.options(),
                    _vehicle_options(),
                    route_preview is not None,
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        if payload.get("lifting_hours") == "":
            payload["lifting_hours"] = None
        if payload.get("vehicle") == "":
            payload["vehicle"] = None
        if payload.get("total_distance_km") == "":
            payload["total_distance_km"] = None

        try:
            validated = CreateDailyOperationRequest.model_validate(payload)
            operation = execute_create(
                validated, create_daily_operation, created_by=caller.user.username
            )
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

        # The estimate is what the planner came for, so it follows the save
        # directly. The operation is stored either way (ADR 0001); only the
        # page differs when no model can produce a number for it yet.
        try:
            prediction = generate_fuel_prediction.execute(operation.operation_id)
        except BaselineModelNotFoundError:
            events.operation_planned(caller.user.username, operation, None)
            return HTMLResponse(
                _render_saved_operation(caller, operation, no_active_model=True),
                status_code=status.HTTP_201_CREATED,
            )
        events.operation_planned(caller.user.username, operation, prediction)
        return HTMLResponse(
            _render_estimate(caller, prediction, operation, similar=_similar(operation)),
            status_code=status.HTTP_201_CREATED,
        )

    @router.get("/riwayat-prediksi", response_class=HTMLResponse)
    def show_history(request: Request, jumlah: int = 0) -> HTMLResponse:
        caller = guard.require_caller(request)
        # The default page is enough for "yesterday"; "?jumlah=" reaches
        # further back, capped so one request cannot pull the whole table.
        limit = min(jumlah, _HISTORY_MAX) if jumlah > 0 else list_recent_predictions.limit
        entries = list_recent_predictions.execute(limit)
        return HTMLResponse(
            render(
                "riwayat-prediksi.html",
                caller=caller,
                page_title="Riwayat Prediksi",
                active_path="/riwayat-prediksi",
                page_lead=(
                    "Estimasi yang pernah dibuat, terbaru di atas. Buka satu untuk melihat "
                    "angkanya lagi atau mencatat BBM aktualnya."
                ),
                entries=entries,
                limit=limit,
                more_limit=min(limit * 4, _HISTORY_MAX) if len(entries) >= limit else None,
            )
        )

    @router.get("/operasi-harian/{operation_id}", response_class=HTMLResponse)
    def show_operation(operation_id: str, request: Request) -> HTMLResponse:
        """One page per operation: its latest estimate, or - if none was ever
        made - the saved operation with the button that makes one."""
        caller = guard.require_caller(request)
        try:
            operation = get_daily_operation.execute(operation_id)
        except DailyOperationNotFoundError:
            return HTMLResponse(
                render(
                    "pesan.html",
                    caller=caller,
                    page_title="Operasi tidak ditemukan",
                    active_path="/riwayat-prediksi",
                    message=f"Tidak ada operasi dengan ID {operation_id}.",
                    back_href="/riwayat-prediksi",
                    back_label="Kembali ke riwayat prediksi",
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        prediction = get_latest_prediction.execute(operation_id)
        if prediction is None:
            return HTMLResponse(_render_saved_operation(caller, operation, no_active_model=False))
        return HTMLResponse(
            _render_estimate(
                caller, prediction, operation, similar=_similar(operation), just_created=False
            )
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
        operation = generate_fuel_prediction.operation_reader.get(operation_id)
        if operation is not None:
            events.operation_planned(caller.user.username, operation, prediction)
        return HTMLResponse(
            _render_estimate(caller, prediction, operation, similar=_similar(operation)),
            status_code=status.HTTP_201_CREATED,
        )

    return router


def _render_saved_operation(
    caller: ActiveCaller, operation: DailyOperation, *, no_active_model: bool
) -> str:
    return render(
        "operasi-tersimpan.html",
        caller=caller,
        page_title="Operasi harian tersimpan",
        active_path="/prediksi",
        operation=operation,
        mode_label=_MODE_LABELS[operation.activity_mode.value],
        source_label=_SOURCE_LABELS[operation.distance_source.value],
        no_active_model=no_active_model,
    )


def _render_estimate(
    caller: ActiveCaller,
    prediction: FuelPrediction,
    operation: DailyOperation | None,
    *,
    similar: tuple[SimilarOperation, ...] = (),
    just_created: bool = True,
) -> str:
    return render(
        "estimasi.html",
        caller=caller,
        page_title="Estimasi kebutuhan bahan bakar",
        active_path="/prediksi" if just_created else "/riwayat-prediksi",
        prediction=prediction,
        operation=operation,
        mode_label=_MODE_LABELS[operation.activity_mode.value] if operation else None,
        similar=similar,
        match_labels=_MATCH_LABELS,
        mode_labels=_MODE_LABELS,
        just_created=just_created,
    )


def _unknown_stop_message(error: UnknownLocationError) -> str:
    if error.ambiguous:
        return (
            f'Pemberhentian "{error.written}" cocok dengan lebih dari satu lokasi: '
            f"{', '.join(error.candidates)}. Pilih salah satu dari daftar."
        )
    if error.candidates:
        return (
            f'Pemberhentian "{error.written}" tidak ada di katalog lokasi. '
            f"Mungkin maksud Anda: {', '.join(error.candidates)}?"
        )
    return f'Pemberhentian "{error.written}" tidak ada di katalog lokasi.'


def _render_form(
    caller: ActiveCaller,
    values: dict[str, Any],
    errors: list[dict[str, str]],
    location_options: tuple[LocationOption, ...],
    vehicle_groups: list[tuple[str, list[tuple[str, str]]]],
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
        vehicle_groups=vehicle_groups,
        location_options=location_options,
        route_preview_available=route_preview_available,
    )
