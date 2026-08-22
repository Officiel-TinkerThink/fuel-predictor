from fuel_predictor.domain.daily_operation import DailyOperation

FEATURE_VERSION = "baseline-v1"


def feature_values(operation: DailyOperation) -> dict[str, str | float]:
    """The sole feature contract used both to fit and score the baseline."""
    return {
        "vehicle_category": operation.vehicle_category.value,
        "activity_mode": operation.activity_mode.value,
        "distance_source": operation.distance_source.value,
        "total_distance_km": operation.total_distance_km,
        "lifting_hours": operation.lifting_hours or 0.0,
    }


def input_snapshot(operation: DailyOperation) -> dict[str, str | float | bool | list[str] | None]:
    return {
        "vehicle_category": operation.vehicle_category.value,
        "activity_mode": operation.activity_mode.value,
        "lifting_hours": operation.lifting_hours,
        "total_distance_km": operation.total_distance_km,
        "distance_source": operation.distance_source.value,
        "stop_sequence": list(operation.stop_sequence),
        "route_distance_manual_fallback": operation.route_distance_manual_fallback,
    }
