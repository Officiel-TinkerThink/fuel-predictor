from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from fuel_predictor.application.routing import (
    RoutingProvider,
    RoutingProviderUnavailable,
    UnavailableRoutingProvider,
)
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DailyOperationValidationError,
    DistanceSource,
    VehicleCategory,
    validate_stop_sequence,
)


class DailyOperationWriter(Protocol):
    def add(self, operation: DailyOperation) -> None: ...


class DailyOperationReader(Protocol):
    def get(self, operation_id: str) -> DailyOperation | None: ...


class DailyOperationNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class CreateDailyOperationCommand:
    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None
    # Optional because a route-sourced plan takes its distance from the
    # provider; it is only needed as the fallback when routing cannot answer.
    total_distance_km: float | None
    distance_source: DistanceSource
    vehicle: str | None = None
    stop_sequence: tuple[str, ...] = ()
    stop_activities: tuple[str, ...] = ()


class CreateDailyOperation:
    def __init__(
        self,
        repository: DailyOperationWriter,
        routing_provider: RoutingProvider | None = None,
        operation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._routing_provider = routing_provider or UnavailableRoutingProvider()
        self._operation_id_factory = operation_id_factory or _new_operation_id

    def execute(self, command: CreateDailyOperationCommand) -> DailyOperation:
        validate_stop_sequence(command.stop_sequence)
        total_distance_km = command.total_distance_km
        distance_source = command.distance_source
        route_distance_manual_fallback = False
        if command.stop_sequence:
            try:
                route_distance = self._routing_provider.calculate_distance(command.stop_sequence)
            except RoutingProviderUnavailable:
                # The route is what the plan asked for, so falling back is a
                # manual distance by definition — and without one there is
                # nothing left to fall back to.
                route_distance_manual_fallback = True
                distance_source = DistanceSource.MANUAL
            else:
                total_distance_km = route_distance.total_distance_km
                distance_source = DistanceSource.ROUTING_PROVIDER
        if total_distance_km is None:
            raise DailyOperationValidationError(
                "total_distance_km",
                "Rute tidak dapat dihitung. Isi jarak total cadangan untuk melanjutkan.",
            )
        operation = DailyOperation(
            operation_id=self._operation_id_factory(),
            vehicle_category=command.vehicle_category,
            vehicle=command.vehicle,
            activity_mode=command.activity_mode,
            lifting_hours=command.lifting_hours,
            total_distance_km=total_distance_km,
            distance_source=distance_source,
            stop_sequence=command.stop_sequence,
            stop_activities=command.stop_activities,
            route_distance_manual_fallback=route_distance_manual_fallback,
        )
        self._repository.add(operation)
        return operation


class GetDailyOperation:
    def __init__(self, repository: DailyOperationReader) -> None:
        self._repository = repository

    def execute(self, operation_id: str) -> DailyOperation:
        operation = self._repository.get(operation_id)
        if operation is None:
            raise DailyOperationNotFoundError(operation_id)
        return operation


def _new_operation_id() -> str:
    return f"OPR-{uuid4().hex.upper()}"
