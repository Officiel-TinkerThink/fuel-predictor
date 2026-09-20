from fuel_predictor.application.vehicles import VehicleLineage
from fuel_predictor.domain.daily_operation import DailyOperation

# Bumped from baseline-v1 when the individual vehicle became a feature. The
# scoring pipeline maps feature names to columns, so a model trained on v1
# simply ignores the new key rather than failing — but the version has to move
# so a package built for one contract is never silently scored under the other.
FEATURE_VERSION = "baseline-v2"

# Contracts whose features depend on the vehicle's type or group (ADR 0015).
# A model trained under one of these can be invalidated by the owner editing
# the catalog, so monitoring compares its catalog fingerprint with the current
# one — and only for these: baseline-v2 reads the instance alone, and warning
# it about a re-typing would be noise. A contract that starts reading
# `lineage` below must add itself here.
LINEAGE_AWARE_FEATURE_VERSIONS: frozenset[str] = frozenset()


def _vehicle_of(operation: DailyOperation) -> str:
    """Unrecorded is its own category, not a missing value: a model can learn
    that operations without a named vehicle behave differently."""
    return operation.vehicle or "tidak diketahui"


def feature_values(operation: DailyOperation, lineage: VehicleLineage) -> dict[str, str | float]:
    """The sole feature contract used both to fit and score the baseline.

    `lineage` is what the catalog says about the operation's vehicle at this
    moment (type and group). baseline-v2 does not read it: the instance name
    is the feature. It is an argument all the same so that every caller — the
    trainer, the scorer, the candidate evaluation — already resolves it, and
    the contract that pools by type or group changes this file alone.
    """
    return {
        "vehicle_category": operation.vehicle_category.value,
        "vehicle": _vehicle_of(operation),
        "activity_mode": operation.activity_mode.value,
        "distance_source": operation.distance_source.value,
        "total_distance_km": operation.total_distance_km,
        "lifting_hours": operation.lifting_hours or 0.0,
    }


def input_snapshot(
    operation: DailyOperation, lineage: VehicleLineage
) -> dict[str, str | float | bool | list[str] | None]:
    """What the prediction was made from, for the record.

    Type and group are written here as the lens that was applied that day —
    traceability, not a source: training and scoring always ask the catalog
    again (ADR 0015).
    """
    return {
        "vehicle_category": operation.vehicle_category.value,
        "vehicle": _vehicle_of(operation),
        "vehicle_type": lineage.type,
        "vehicle_group": lineage.group,
        "activity_mode": operation.activity_mode.value,
        "lifting_hours": operation.lifting_hours,
        "total_distance_km": operation.total_distance_km,
        "distance_source": operation.distance_source.value,
        "stop_sequence": list(operation.stop_sequence),
        "route_distance_manual_fallback": operation.route_distance_manual_fallback,
    }
