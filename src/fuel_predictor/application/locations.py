from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LocationOption:
    name: str
    latitude: float
    longitude: float


class LocationCatalog(Protocol):
    """Port for the planner's known stop points (name to coordinates)."""

    def options(self) -> tuple[LocationOption, ...]: ...

    def find(self, name: str) -> LocationOption | None: ...
