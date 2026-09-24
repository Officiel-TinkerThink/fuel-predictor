import csv
from importlib import resources
from pathlib import Path

from fuel_predictor.application.vehicles import (
    VehicleLineage,
    VehicleOption,
    check_catalog,
    lineage_from,
)

# Package data, for the same reason as the location catalog and the model
# schemas: resolving it by walking up from __file__ works from a checkout and
# breaks once installed. This CSV is an export of the planner's "Dim_Kendaraan"
# sheet, with the alias column taken from "Peta_Nama_Sumber".
_CATALOG_PATH = Path(str(resources.files("fuel_predictor") / "examples" / "kendaraan-angber.csv"))


def _keys(option: VehicleOption) -> tuple[str, ...]:
    """Every spelling that should resolve to this vehicle.

    Spaces are dropped as well as case folded, because the sheets write the same
    unit as "VT 01", "VT01" and "vt 01" interchangeably.
    """
    written = (option.name, *option.aliases)
    return tuple(name.casefold().replace(" ", "") for name in written if name)


def _yes(value: str | None) -> bool:
    """A sheet's "ya"/"tidak" (or yes/true/1). Blank means no: a unit is
    mobilisation only until the sheet says it can lift."""
    return (value or "").strip().casefold() in {"ya", "yes", "true", "1", "y"}


class PackagedVehicleCatalog:
    """Reads the bundled fleet once and serves it from memory."""

    def __init__(self, source: Path | None = None) -> None:
        path = source or _CATALOG_PATH
        options: list[VehicleOption] = []
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                aliases = tuple(
                    alias.strip() for alias in (row.get("alias") or "").split(";") if alias.strip()
                )
                # A sheet without a `tipe` column, or with a blank cell, means
                # the group has one type: it is named after the group.
                options.append(
                    VehicleOption(
                        name=row["nama_kendaraan"].strip(),
                        group=(row.get("grup") or "").strip(),
                        aliases=aliases,
                        type=(row.get("tipe") or "").strip(),
                        group_code=(row.get("kode_grup") or "").strip(),
                        type_code=(row.get("kode_tipe") or "").strip(),
                        can_lift=_yes(row.get("bisa_lifting")),
                    )
                )
        check_catalog(options)
        self._options = tuple(options)
        self._by_key = {key: option for option in options for key in _keys(option)}

    def options(self) -> tuple[VehicleOption, ...]:
        return self._options

    def find(self, name: str) -> VehicleOption | None:
        return self._by_key.get(name.strip().casefold().replace(" ", ""))

    def lineage_of(self, name: str | None) -> VehicleLineage:
        return lineage_from(self.find(name) if name else None)
