"""The fleet as the catalog holds it, for anyone who writes vehicle codes down."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.vehicles import VehicleCatalog, VehicleOption
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard


def build_fleet_pages_router(vehicle_catalog: VehicleCatalog, guard: SecurityGuard) -> APIRouter:
    router = APIRouter()

    @router.get("/armada", response_class=HTMLResponse)
    def show_fleet(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        # By group, then by name: VT 01, VT 02, … is how people look a unit up.
        units = tuple(
            sorted(vehicle_catalog.options(), key=lambda unit: (unit.group_code or "~", unit.name))
        )
        example = _example(units)
        return HTMLResponse(
            render(
                "armada.html",
                caller=caller,
                page_title="Armada",
                active_path="/armada",
                page_lead=(
                    "Setiap kendaraan punya kode: grup, tipe, lalu unitnya. Kode ini yang "
                    "tertulis di setiap kode operasi."
                ),
                units=units,
                example=example,
            )
        )

    return router


def _example(units: tuple[VehicleOption, ...]) -> VehicleOption | None:
    """A unit to spell a code out with: the first fully coded one of the
    largest group, so the example is a machine most readers work with."""
    coded = [unit for unit in units if unit.group_code and unit.type_code]
    if not coded:
        return None
    sizes = {
        group: sum(unit.group == group for unit in units) for group in {u.group for u in coded}
    }
    return min(coded, key=lambda unit: (-sizes[unit.group], unit.name))
