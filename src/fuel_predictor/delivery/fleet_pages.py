"""The fleet as the catalog holds it, for anyone who writes vehicle codes down."""

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fuel_predictor.application.vehicles import VehicleCatalog, VehicleOption
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard


@dataclass(frozen=True, slots=True)
class _TypeSummary:
    name: str
    code: str
    units: tuple[VehicleOption, ...]


@dataclass(frozen=True, slots=True)
class _GroupSummary:
    name: str
    code: str
    types: tuple[_TypeSummary, ...]


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
                groups=_summarise(units),
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


def _summarise(units: tuple[VehicleOption, ...]) -> tuple[_GroupSummary, ...]:
    """Group -> type -> units, each level in the order its code sorts."""
    groups: dict[tuple[str, str], dict[tuple[str, str], list[VehicleOption]]] = {}
    for unit in units:
        types = groups.setdefault((unit.group, unit.group_code), {})
        types.setdefault((unit.type, unit.type_code), []).append(unit)
    return tuple(
        _GroupSummary(
            name=group,
            code=group_code,
            types=tuple(
                _TypeSummary(name=type_name, code=type_code, units=tuple(members))
                for (type_name, type_code), members in sorted(
                    types.items(), key=lambda item: (item[0][1] or "~", item[0][0])
                )
            ),
        )
        for (group, group_code), types in sorted(
            groups.items(), key=lambda item: (item[0][1] or "~", item[0][0])
        )
    )
