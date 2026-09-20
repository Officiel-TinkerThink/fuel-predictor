from collections.abc import Iterable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

# The value every level takes when a unit is not in the catalog. Its own
# category rather than a missing value: a model can learn that operations with
# an unrecorded vehicle behave differently, and a ranking can say so plainly.
UNKNOWN_VEHICLE = "tidak diketahui"


@dataclass(frozen=True, slots=True)
class VehicleOption:
    """A vehicle the fleet actually runs, as the planner's sheets name it.

    Every unit sits in a three-level lineage (ADR 0015): the unit itself, its
    `type`, and its `group` — the kind of machine: Crane, Truck, Forklift,
    Vacuum Truck. The type is the owner's finer cut inside a group ("VT A" among
    the vacuum trucks). A group with a single type names that type after itself,
    which is every group today; the level exists so that splitting one later
    is an edit of a few cells, not a schema change.
    """

    name: str
    group: str
    # Other spellings the same vehicle appears under. The operational sheets
    # have never been consistent, and the workbook already keeps this mapping,
    # so importing history means resolving "PM 01" back to "Prime Mover".
    aliases: tuple[str, ...] = field(default=())
    # Defaults to the group: see the class docstring. Kept after `aliases` so
    # the many places that build an option positionally keep working.
    type: str = ""

    def __post_init__(self) -> None:
        if not self.type:
            object.__setattr__(self, "type", self.group)

    @property
    def lineage(self) -> "VehicleLineage":
        return VehicleLineage(
            vehicle=self.name,
            type=self.type or UNKNOWN_VEHICLE,
            group=self.group or UNKNOWN_VEHICLE,
        )


@dataclass(frozen=True, slots=True)
class VehicleLineage:
    """What the catalog says about a written vehicle name, at every level.

    This is what the feature contract and the similar-operations ranking are
    handed. It is derived from the catalog at the moment it is needed, never
    stored as a source of truth: the taxonomy is a lens the owner may refine,
    and every reading of history must see the same lens (ADR 0015).
    """

    vehicle: str
    type: str
    group: str

    @classmethod
    def unknown(cls) -> "VehicleLineage":
        return cls(vehicle=UNKNOWN_VEHICLE, type=UNKNOWN_VEHICLE, group=UNKNOWN_VEHICLE)


class VehicleCatalog(Protocol):
    """Port for the fleet: what may be chosen, and what a written name means."""

    def options(self) -> tuple[VehicleOption, ...]: ...

    def find(self, name: str) -> VehicleOption | None: ...

    def lineage_of(self, name: str | None) -> VehicleLineage: ...


def catalog_fingerprint(options: Iterable[VehicleOption]) -> str:
    """One short string that changes when the taxonomy does.

    Hashes the sorted `(unit, type, group)` triples — not aliases, not row
    order — so a model can record which grouping it was trained under and
    monitoring can tell when the owner has since edited it (ADR 0015).
    """
    lines = sorted(f"{option.name}\t{option.type}\t{option.group}" for option in options)
    return sha256("\n".join(lines).encode("utf-8")).hexdigest()


def lineage_from(option: VehicleOption | None) -> VehicleLineage:
    """The one rule both catalogs share: a found option's lineage, otherwise
    unknown at every level. Never raises, because feature time is not the
    place to discover a catalog gap."""
    return option.lineage if option is not None else VehicleLineage.unknown()


def written_name_key(name: str) -> str:
    """How every spelling of a unit is matched: case folded, spaces dropped,
    because the sheets write "VT 01", "VT01" and "vt 01" interchangeably."""
    return name.strip().casefold().replace(" ", "")


class LineageIndex:
    """The catalog read once and answered from memory.

    A trainer walks thousands of rows and an evaluation walks every case; a
    catalog backed by a table must not be queried for each of them. Build
    this from `catalog.options()` at the start of the batch and ask it instead.
    """

    def __init__(self, options: Iterable[VehicleOption]) -> None:
        self._by_key: dict[str, VehicleOption] = {}
        for option in options:
            for written in (option.name, *option.aliases):
                if written:
                    self._by_key.setdefault(written_name_key(written), option)

    def find(self, name: str) -> VehicleOption | None:
        return self._by_key.get(written_name_key(name))

    def lineage_of(self, name: str | None) -> VehicleLineage:
        return lineage_from(self.find(name) if name else None)
