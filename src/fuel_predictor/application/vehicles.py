from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VehicleOption:
    """A vehicle the fleet actually runs, as the planner's sheets name it.

    `group` is the kind of machine — Crane, Truck, Forklift, Vacuum Truck — so a
    model can share what one kind has in common while still telling two units of
    that kind apart.
    """

    name: str
    group: str
    # Other spellings the same vehicle appears under. The operational sheets
    # have never been consistent, and the workbook already keeps this mapping,
    # so importing history means resolving "PM 01" back to "Prime Mover".
    aliases: tuple[str, ...] = field(default=())


class VehicleCatalog(Protocol):
    """Port for the fleet: what may be chosen, and what a written name means."""

    def options(self) -> tuple[VehicleOption, ...]: ...

    def find(self, name: str) -> VehicleOption | None: ...
