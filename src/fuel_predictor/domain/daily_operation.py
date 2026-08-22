from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class VehicleCategory(StrEnum):
    ANGBER = "ANGBER"


class ActivityMode(StrEnum):
    TRANSPORT = "transport"
    LIFTING = "lifting"
    TRANSPORT_AND_LIFTING = "transport_and_lifting"


class DistanceSource(StrEnum):
    MANUAL = "manual"
    ROUTING_PROVIDER = "routing_provider"


class DailyOperationValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class DailyOperation:
    operation_id: str
    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None
    total_distance_km: float
    distance_source: DistanceSource
    stop_sequence: tuple[str, ...] = ()
    route_distance_manual_fallback: bool = False

    def __post_init__(self) -> None:
        if not isfinite(self.total_distance_km) or self.total_distance_km <= 0:
            raise DailyOperationValidationError(
                "total_distance_km", "Jarak total harus lebih besar dari 0."
            )

        includes_lifting = self.activity_mode in {
            ActivityMode.LIFTING,
            ActivityMode.TRANSPORT_AND_LIFTING,
        }
        if includes_lifting and (
            self.lifting_hours is None
            or not isfinite(self.lifting_hours)
            or self.lifting_hours <= 0
        ):
            raise DailyOperationValidationError(
                "lifting_hours",
                "Jam lifting harus lebih besar dari 0 untuk mode yang mencakup lifting.",
            )
        if not includes_lifting and self.lifting_hours is not None:
            raise DailyOperationValidationError(
                "lifting_hours", "Jam lifting harus dikosongkan untuk mode transport."
            )

        validate_stop_sequence(self.stop_sequence)
        if self.route_distance_manual_fallback and (
            not self.stop_sequence or self.distance_source is not DistanceSource.MANUAL
        ):
            raise DailyOperationValidationError(
                "route_distance_manual_fallback",
                "Fallback jarak manual hanya berlaku untuk urutan pemberhentian "
                "saat rute tidak tersedia.",
            )


def validate_stop_sequence(stop_sequence: tuple[str, ...]) -> None:
    if stop_sequence and len(stop_sequence) < 2:
        raise DailyOperationValidationError(
            "stop_sequence", "Urutan pemberhentian harus berisi setidaknya dua lokasi."
        )
    if any(not stop.strip() for stop in stop_sequence):
        raise DailyOperationValidationError(
            "stop_sequence", "Nama setiap pemberhentian wajib diisi."
        )
