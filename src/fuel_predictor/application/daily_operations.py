from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime, tzinfo
from typing import Protocol
from uuid import uuid4

from fuel_predictor.application.routing import (
    RoutingProvider,
    RoutingProviderUnavailable,
    UnavailableRoutingProvider,
)
from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DailyOperationValidationError,
    DistanceSource,
    VehicleCategory,
    validate_stop_sequence,
)
from fuel_predictor.domain.operation_code import (
    next_free_operation_code,
    normalize_operation_reference,
    operation_code_base,
    vehicle_code,
)


class DailyOperationWriter(Protocol):
    def add(self, operation: DailyOperation) -> None:
        """Store the operation; raise OperationCodeTakenError if its code is held."""
        ...

    def codes_taken(self, base: str) -> Collection[str]:
        """The stored codes that are `base` itself or `base` with a suffix."""
        ...


class DailyOperationReader(Protocol):
    def get(self, operation_id: str) -> DailyOperation | None: ...


class DailyOperationLookup(DailyOperationReader, Protocol):
    def get_by_code(self, operation_code: str) -> DailyOperation | None: ...


class DailyOperationNotFoundError(LookupError):
    pass


class OperationCodeTakenError(ValueError):
    """Another operation was stored with this code first."""


# Each retry means another request stored the same vehicle in the same minute
# between our lookup and our insert. More than a few in a row is not a race.
_CODE_ATTEMPTS = 5


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
    # The signed-in username, or an agent client's name; None from a caller
    # that identifies itself no further.
    created_by: str | None = None


class CreateDailyOperation:
    def __init__(
        self,
        repository: DailyOperationWriter,
        routing_provider: RoutingProvider | None = None,
        operation_id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
        site_timezone: tzinfo = UTC,
        vehicle_catalog: VehicleCatalog | None = None,
    ) -> None:
        self._repository = repository
        self._routing_provider = routing_provider or UnavailableRoutingProvider()
        self._operation_id_factory = operation_id_factory or _new_operation_id
        self._now = now or (lambda: datetime.now(UTC))
        self._site_timezone = site_timezone
        self._vehicle_catalog = vehicle_catalog

    def execute(self, command: CreateDailyOperationCommand) -> DailyOperation:
        validate_stop_sequence(command.stop_sequence)
        self._refuse_lifting_without_capacity(command)
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
                "Rute tidak dapat dihitung. Masukkan jarak tempuh manual untuk melanjutkan.",
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
            created_by=command.created_by,
            created_at=self._now(),
        )
        return self._store_with_code(operation)

    def _store_with_code(self, operation: DailyOperation) -> DailyOperation:
        assert operation.created_at is not None
        base = operation_code_base(
            operation.created_at.astimezone(self._site_timezone),
            self._vehicle_code(operation.vehicle),
        )
        for _ in range(_CODE_ATTEMPTS):
            coded = replace(
                operation,
                operation_code=next_free_operation_code(base, self._repository.codes_taken(base)),
            )
            try:
                self._repository.add(coded)
            except OperationCodeTakenError:
                continue
            return coded
        raise OperationCodeTakenError(base)

    def _refuse_lifting_without_capacity(self, command: CreateDailyOperationCommand) -> None:
        """A unit the catalog says cannot lift is mobilisation only. A unit the
        catalog does not know is not second-guessed: there is nothing to check."""
        if command.activity_mode is ActivityMode.TRANSPORT or not command.vehicle:
            return
        option = self._vehicle_catalog.find(command.vehicle) if self._vehicle_catalog else None
        if option is not None and not option.can_lift:
            raise DailyOperationValidationError(
                "activity_mode",
                f"{option.name} tidak memiliki kemampuan lifting. Pilih Mobilisasi.",
            )

    def _vehicle_code(self, vehicle: str | None) -> str | None:
        """The catalog's group - type - unit code for the unit, under whatever
        spelling it was written; a unit the catalog does not know keeps its mark."""
        option = self._vehicle_catalog.find(vehicle) if vehicle and self._vehicle_catalog else None
        return option.vehicle_code if option is not None else vehicle_code("", "", vehicle)


class GetDailyOperation:
    def __init__(self, repository: DailyOperationReader) -> None:
        self._repository = repository

    def execute(self, operation_id: str) -> DailyOperation:
        operation = self._repository.get(operation_id)
        if operation is None:
            raise DailyOperationNotFoundError(operation_id)
        return operation


def find_daily_operation(lookup: DailyOperationLookup, reference: str) -> DailyOperation:
    """The operation a person pointed at, by its operation code or its `OPR-…` id.

    Codes are what people write down (ADR 0016); ids still arrive from links,
    older sheets and API clients. Either is read ignoring case and spaces.
    """
    normalized = normalize_operation_reference(reference)
    operation = lookup.get(reference.strip()) or lookup.get_by_code(normalized)
    if operation is None:
        raise DailyOperationNotFoundError(reference)
    return operation


def _new_operation_id() -> str:
    return f"OPR-{uuid4().hex.upper()}"
