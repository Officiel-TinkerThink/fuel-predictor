from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from fuel_predictor.application.routing import RouteDistance, RoutingProviderUnavailable
from fuel_predictor.infrastructure.google_maps_routing import GoogleMapsRoutesProvider
from fuel_predictor.main import create_app


class RoutingProvider(Protocol):
    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance: ...


class RecordingRoutingProvider:
    def __init__(self, distance_km: float) -> None:
        self.distance_km = distance_km
        self.submitted_sequences: list[tuple[str, ...]] = []

    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance:
        self.submitted_sequences.append(stop_sequence)
        return RouteDistance(total_distance_km=self.distance_km, provider_name="test-routing")


class UnavailableRoutingProvider:
    def calculate_distance(self, stop_sequence: tuple[str, ...]) -> RouteDistance:
        raise RoutingProviderUnavailable("Layanan rute sedang tidak tersedia.")


class GoogleMapsRoutesResponseStub:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return self._body


class GoogleMapsRoutesClientStub:
    def __init__(self, waypoint_order: list[int] | None = None) -> None:
        self.waypoint_order = waypoint_order
        self.calls: list[dict[str, object]] = []

    def post(self, _url: str, **kwargs: object) -> GoogleMapsRoutesResponseStub:
        self.calls.append(kwargs)
        route: dict[str, object] = {
            "distanceMeters": 20_000,
        }
        if self.waypoint_order is not None:
            route["optimizedIntermediateWaypointIndex"] = self.waypoint_order
        return GoogleMapsRoutesResponseStub({"routes": [route]})


def _train_baseline(client: TestClient) -> None:
    historical_csv = (
        "Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
        "Bahan Bakar Disiapkan (L),Sumber Jarak\n"
        "ANGBER,transport,,20,18,manual\n"
        "ANGBER,transport,,40,28,manual\n"
    )
    dataset = client.post(
        "/api/v1/historical-datasets",
        files={"file": ("riwayat.csv", historical_csv.encode(), "text/csv")},
    ).json()["dataset_version"]
    response = client.post(
        f"/api/v1/dataset-versions/{dataset['dataset_version_id']}/baseline-candidates"
    )
    assert response.status_code == 201
    promoted = client.post(
        f"/api/v1/model-candidates/{response.json()['model_version_id']}/promote"
    )
    assert promoted.status_code == 200


def test_calculated_distance_uses_exact_planner_stop_order_and_becomes_prediction_feature(
    tmp_path: Path,
) -> None:
    provider = RecordingRoutingProvider(distance_km=86.4)
    submitted_stops = ["Depo", "Site A", "Site B", "Depo"]
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", routing_provider=provider)
    ) as client:
        _train_baseline(client)
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 1,
                "distance_source": "manual",
                "stop_sequence": submitted_stops,
            },
        )
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert operation.status_code == 201
    assert provider.submitted_sequences == [tuple(submitted_stops)]
    assert operation.json()["stop_sequence"] == submitted_stops
    assert operation.json()["total_distance_km"] == 86.4
    assert operation.json()["distance_source"] == "routing_provider"
    assert operation.json()["route_distance_manual_fallback"] is False
    assert prediction.status_code == 201
    assert prediction.json()["route_distance_source"] == "routing_provider"
    assert prediction.json()["route_distance_manual_fallback"] is False
    assert prediction.json()["input_snapshot"]["stop_sequence"] == submitted_stops
    assert prediction.json()["input_snapshot"]["total_distance_km"] == 86.4
    assert prediction.json()["feature_values"]["total_distance_km"] == 86.4


def test_unavailable_routing_allows_visible_manual_distance_fallback(tmp_path: Path) -> None:
    with TestClient(
        create_app(
            database_path=tmp_path / "operations.sqlite3",
            routing_provider=UnavailableRoutingProvider(),
        )
    ) as client:
        _train_baseline(client)
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 72.5,
                "distance_source": "manual",
                "stops": ["Depo", "Tambang", "Depo"],
            },
        )
        prediction = client.post(
            f"/api/v1/daily-operations/{operation.json()['operation_id']}/predictions"
        )

    assert operation.status_code == 201
    assert operation.json()["total_distance_km"] == 72.5
    assert operation.json()["distance_source"] == "manual"
    assert operation.json()["route_distance_manual_fallback"] is True
    assert prediction.status_code == 201
    assert prediction.json()["route_distance_source"] == "manual"
    assert prediction.json()["route_distance_manual_fallback"] is True
    assert prediction.json()["input_snapshot"]["route_distance_manual_fallback"] is True


def test_indonesian_form_exposes_ordered_stop_controls_and_submits_them(tmp_path: Path) -> None:
    provider = RecordingRoutingProvider(distance_km=42)
    with TestClient(
        create_app(database_path=tmp_path / "operations.sqlite3", routing_provider=provider)
    ) as client:
        form = client.get("/prediksi")
        response = client.post(
            "/operasi-harian",
            content=urlencode(
                [
                    ("vehicle_category", "ANGBER"),
                    ("activity_mode", "transport"),
                    ("total_distance_km", "50"),
                    ("distance_source", "manual"),
                    ("stop_sequence", "Depo"),
                    ("stop_sequence", "Site A"),
                    ("stop_sequence", "Depo"),
                ]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert form.status_code == 200
    assert "Tambah pemberhentian" in form.text
    assert "Naikkan urutan pemberhentian" in form.text
    assert "Turunkan urutan pemberhentian" in form.text
    assert "Hapus pemberhentian" in form.text
    assert response.status_code == 201
    assert provider.submitted_sequences == [("Depo", "Site A", "Depo")]
    assert "42 km" in response.text


def test_google_maps_adapter_disables_optimization_and_rejects_reordered_waypoints() -> None:
    client = GoogleMapsRoutesClientStub(waypoint_order=[0, 1])
    provider = GoogleMapsRoutesProvider("unused-in-test", client=client)

    route = provider.calculate_distance(("Depo", "Site A", "Site B", "Depo"))

    assert route.total_distance_km == 20
    assert client.calls == [
        {
            "headers": {
                "X-Goog-Api-Key": "unused-in-test",
                "X-Goog-FieldMask": (
                    "routes.distanceMeters,routes.optimizedIntermediateWaypointIndex"
                ),
            },
            "json": {
                "origin": {"address": "Depo"},
                "destination": {"address": "Depo"},
                "intermediates": [{"address": "Site A"}, {"address": "Site B"}],
                "travelMode": "DRIVE",
                "optimizeWaypointOrder": False,
            },
        }
    ]

    reordered = GoogleMapsRoutesProvider(
        "unused-in-test", client=GoogleMapsRoutesClientStub(waypoint_order=[1, 0])
    )
    try:
        reordered.calculate_distance(("Depo", "Site A", "Site B", "Depo"))
    except RoutingProviderUnavailable:
        pass
    else:
        raise AssertionError("Adapter must reject a reordered route response.")
