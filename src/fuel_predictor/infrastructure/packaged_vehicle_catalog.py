import csv
from importlib import resources
from pathlib import Path

from fuel_predictor.application.vehicles import VehicleOption

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
                options.append(
                    VehicleOption(
                        name=row["nama_kendaraan"].strip(),
                        group=(row.get("grup") or "").strip(),
                        aliases=aliases,
                    )
                )
        self._options = tuple(options)
        self._by_key = {key: option for option in options for key in _keys(option)}

    def options(self) -> tuple[VehicleOption, ...]:
        return self._options

    def find(self, name: str) -> VehicleOption | None:
        return self._by_key.get(name.strip().casefold().replace(" ", ""))
