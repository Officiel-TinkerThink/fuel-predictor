import csv
from importlib import resources
from pathlib import Path

from fuel_predictor.application.locations import LocationOption

# Resolved as package data, not by walking up from __file__, for the same
# reason as the model-package schemas and the demo historical dataset: that
# breaks the moment the package is pip-installed. This CSV is a cleaned
# export of the planner's "Data Lokasi" reference sheet (name, decimal
# latitude, decimal longitude).
_CATALOG_PATH = Path(str(resources.files("fuel_predictor") / "examples" / "lokasi-angber.csv"))


class PackagedLocationCatalog:
    """Reads the bundled location list once and serves it from memory."""

    def __init__(self, source: Path | None = None) -> None:
        path = source or _CATALOG_PATH
        options: list[LocationOption] = []
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                options.append(
                    LocationOption(
                        name=row["nama_lokasi"],
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                    )
                )
        self._options = tuple(options)
        self._by_name = {option.name.strip().casefold(): option for option in options}

    def options(self) -> tuple[LocationOption, ...]:
        return self._options

    def find(self, name: str) -> LocationOption | None:
        return self._by_name.get(name.strip().casefold())
