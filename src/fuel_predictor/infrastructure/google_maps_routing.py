from typing import Any

import httpx

from fuel_predictor.application.locations import LocationCatalog
from fuel_predictor.application.routing import (
    RouteDistance,
    RoutePreview,
    RoutingProviderUnavailable,
)

_COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_ROUTE_FIELD_MASK = "routes.distanceMeters,routes.optimizedIntermediateWaypointIndex"
_PREVIEW_FIELD_MASK = "routes.distanceMeters,routes.polyline.encodedPolyline"


class GoogleMapsRoutesProvider:
    """Google Routes API adapter that preserves the planner's stop order."""

    def __init__(
        self,
        api_key: str,
        client: Any | None = None,
        location_catalog: LocationCatalog | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None
        self._location_catalog = location_catalog

    def _waypoint(self, stop: str) -> dict[str, Any]:
        """A known stop resolves to its surveyed lat/lng; anything else is geocoded by address."""
        match = self._location_catalog.find(stop) if self._location_catalog else None
        if match is None:
            return {"address": stop}
        return {"location": {"latLng": {"latitude": match.latitude, "longitude": match.longitude}}}

    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance:
        try:
            response = self._client.post(
                _COMPUTE_ROUTES_URL,
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": _ROUTE_FIELD_MASK,
                },
                json={
                    "origin": self._waypoint(stop_sequence[0]),
                    "destination": self._waypoint(stop_sequence[-1]),
                    "intermediates": [self._waypoint(stop) for stop in stop_sequence[1:-1]],
                    "travelMode": "DRIVE",
                    "optimizeWaypointOrder": False,
                },
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
        except Exception as error:
            raise RoutingProviderUnavailable(
                "Penyedia rute tidak dapat dihubungi. "
                "Masukkan jarak total manual untuk melanjutkan."
            ) from error

        if not routes:
            raise RoutingProviderUnavailable(
                "Penyedia rute tidak menemukan rute. Masukkan jarak total manual untuk melanjutkan."
            )
        route = routes[0]
        waypoint_order = route.get("optimizedIntermediateWaypointIndex")
        expected_order = list(range(len(stop_sequence) - 2))
        if waypoint_order is not None and waypoint_order != expected_order:
            raise RoutingProviderUnavailable(
                "Penyedia rute mencoba mengubah urutan pemberhentian. "
                "Masukkan jarak total manual untuk melanjutkan."
            )
        try:
            distance_meters = float(route["distanceMeters"])
        except (KeyError, TypeError, ValueError) as error:
            raise RoutingProviderUnavailable(
                "Penyedia rute mengembalikan jarak yang tidak dapat digunakan. "
                "Masukkan jarak total manual untuk melanjutkan."
            ) from error
        try:
            return RouteDistance(
                total_distance_km=distance_meters / 1000,
                provider_name="google_maps",
            )
        except ValueError as error:
            raise RoutingProviderUnavailable(
                "Penyedia rute mengembalikan jarak yang tidak dapat digunakan. "
                "Masukkan jarak total manual untuk melanjutkan."
            ) from error

    def preview_route(self, stop_sequence: tuple[str, ...]) -> RoutePreview:
        """The route as drawn, so the planner sees it before committing to it."""
        try:
            response = self._client.post(
                _COMPUTE_ROUTES_URL,
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": _PREVIEW_FIELD_MASK,
                },
                json={
                    "origin": self._waypoint(stop_sequence[0]),
                    "destination": self._waypoint(stop_sequence[-1]),
                    "intermediates": [self._waypoint(stop) for stop in stop_sequence[1:-1]],
                    "travelMode": "DRIVE",
                    "optimizeWaypointOrder": False,
                },
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
        except Exception as error:
            raise RoutingProviderUnavailable(
                "Penyedia rute tidak dapat dihubungi untuk pratinjau."
            ) from error

        if not routes:
            raise RoutingProviderUnavailable("Penyedia rute tidak menemukan rute untuk pratinjau.")
        try:
            distance_meters = float(routes[0]["distanceMeters"])
            polyline = str(routes[0]["polyline"]["encodedPolyline"])
        except (KeyError, TypeError, ValueError) as error:
            raise RoutingProviderUnavailable(
                "Penyedia rute mengembalikan pratinjau yang tidak dapat digunakan."
            ) from error
        return RoutePreview(
            total_distance_km=distance_meters / 1000, encoded_polyline=polyline
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
