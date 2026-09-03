from dataclasses import dataclass
from math import isfinite
from typing import Protocol


class RoutingProviderUnavailable(RuntimeError):
    """Raised when a route provider cannot safely resolve a submitted route."""


@dataclass(frozen=True, slots=True)
class RouteDistance:
    total_distance_km: float
    provider_name: str

    def __post_init__(self) -> None:
        if not isfinite(self.total_distance_km) or self.total_distance_km <= 0:
            raise ValueError("Jarak dari penyedia rute harus lebih besar dari 0.")


@dataclass(frozen=True, slots=True)
class RoutePreview:
    """The drawn route behind the planner's stop order, for the preview panel."""

    total_distance_km: float
    encoded_polyline: str


class RoutingProvider(Protocol):
    """Port for distance calculation in the planner's submitted stop order."""

    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance: ...


class RoutePreviewProvider(Protocol):
    """Port for showing the route while it is still being planned.

    Separate from `RoutingProvider` because previewing is optional: an
    installation with no routing service still plans operations, it just does
    not draw them.
    """

    def preview_route(self, stop_sequence: tuple[str, ...]) -> RoutePreview: ...


class UnavailableRoutingProvider:
    """Safe default when no routing service is configured for the local installation."""

    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance:
        raise RoutingProviderUnavailable(
            "Penyedia rute tidak tersedia. Masukkan jarak total manual untuk melanjutkan."
        )
