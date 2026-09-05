from fuel_predictor.domain.daily_operation import DailyOperation

# Bumped from baseline-v1 when the individual vehicle became a feature. The
# scoring pipeline maps feature names to columns, so a model trained on v1
# simply ignores the new key rather than failing — but the version has to move
# so a package built for one contract is never silently scored under the other.
FEATURE_VERSION = "baseline-v2"


def _vehicle_of(operation: DailyOperation) -> str:
    """Unrecorded is its own category, not a missing value: a model can learn
    that operations without a named vehicle behave differently."""
    return operation.vehicle.value if operation.vehicle else "tidak diketahui"


def feature_values(operation: DailyOperation) -> dict[str, str | float]:
    """The sole feature contract used both to fit and score the baseline."""
    return {
        "vehicle_category": operation.vehicle_category.value,
        "vehicle": _vehicle_of(operation),
        "activity_mode": operation.activity_mode.value,
        "distance_source": operation.distance_source.value,
        "total_distance_km": operation.total_distance_km,
        "lifting_hours": operation.lifting_hours or 0.0,
    }


def input_snapshot(operation: DailyOperation) -> dict[str, str | float | bool | list[str] | None]:
    return {
        "vehicle_category": operation.vehicle_category.value,
        "vehicle": _vehicle_of(operation),
        "activity_mode": operation.activity_mode.value,
        "lifting_hours": operation.lifting_hours,
        "total_distance_km": operation.total_distance_km,
        "distance_source": operation.distance_source.value,
        "stop_sequence": list(operation.stop_sequence),
        "route_distance_manual_fallback": operation.route_distance_manual_fallback,
    }
