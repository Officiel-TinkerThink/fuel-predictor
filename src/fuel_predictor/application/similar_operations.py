"""Past operations that resemble the one being planned.

A recommendation is a number; what makes a planner trust it is seeing what the
same crane needed on a similar day. This use case finds those days from both
places the system keeps history:

- the imported dataset the active model learned from (prepared fuel only,
  no stop sequence — the sheets never had one), and
- operations recorded through the app or an agent, which carry their stops,
  the estimate given at the time and, once entered, the actual fuel.

They are merged and ranked, not modelled: nothing here adjusts the estimate.
The ranking is deliberately explainable — same unit, then same type, then same
group, then same category (the fallback order ADR 0015 fixes for the whole
application), then same activity, then nearest distance — so the agent can say
*why* a row is shown rather than only that it is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from fuel_predictor.application.vehicles import VehicleCatalog, VehicleLineage
from fuel_predictor.domain.daily_operation import ActivityMode, DistanceSource, VehicleCategory


class HistorySource(StrEnum):
    DATASET = "dataset"
    RECORDED = "recorded"


class VehicleMatch(StrEnum):
    SAME = "same"
    SAME_TYPE = "same_type"
    SAME_GROUP = "same_group"
    SAME_CATEGORY = "same_category"


@dataclass(frozen=True, slots=True)
class HistoricalOperationRecord:
    """One past operation as the port hands it over, before ranking.

    `prepared_fuel_liters` is set for dataset rows; the estimate, allocation
    and actual are set for recorded ones when they exist. A row never has both
    kinds, and the shape keeps that visible instead of collapsing them into one
    ambiguous "fuel" number (ADR 0002).
    """

    source: HistorySource
    operation_id: str
    vehicle: str | None
    vehicle_category: VehicleCategory
    activity_mode: ActivityMode
    lifting_hours: float | None
    total_distance_km: float
    distance_source: DistanceSource
    stop_sequence: tuple[str, ...] | None = None
    prepared_fuel_liters: float | None = None
    estimated_fuel_requirement_liters: float | None = None
    recommended_allocation_liters: float | None = None
    actual_fuel_liters: float | None = None
    recorded_at: datetime | None = None
    # The day the sheet says it happened, as written there ("12/08/2026"). A
    # dataset row has no timestamp of its own, and a planner reading history
    # asks "when was that?" before anything else.
    operation_date: str | None = None
    source_reference: str | None = None


class HistoricalOperationSource(Protocol):
    """Port: where past operations come from. Filtering by category happens
    here so the ranking never has to page through another category's rows."""

    def dataset_operations(
        self, vehicle_category: VehicleCategory
    ) -> Sequence[HistoricalOperationRecord]: ...

    def recorded_operations(
        self, vehicle_category: VehicleCategory
    ) -> Sequence[HistoricalOperationRecord]: ...


@dataclass(frozen=True, slots=True)
class SimilarOperationsQuery:
    vehicle: str
    vehicle_category: VehicleCategory = VehicleCategory.ANGBER
    activity_mode: ActivityMode | None = None
    lifting_hours: float | None = None
    total_distance_km: float | None = None
    limit: int = 10
    # The operation being planned is itself recorded before its history is
    # looked up; without this it would come back as its own closest match.
    exclude_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    vehicle: VehicleMatch
    activity_mode: bool | None
    distance_delta_km: float | None
    lifting_hours_delta: float | None
    score: float


@dataclass(frozen=True, slots=True)
class SimilarOperation:
    record: HistoricalOperationRecord
    vehicle_type: str | None
    vehicle_group: str | None
    match: SimilarityMatch


@dataclass(frozen=True, slots=True)
class FindSimilarOperations:
    source: HistoricalOperationSource
    vehicle_catalog: VehicleCatalog

    def execute(self, query: SimilarOperationsQuery) -> tuple[SimilarOperation, ...]:
        if query.limit <= 0:
            return ()
        wanted = self.vehicle_catalog.find(query.vehicle)
        wanted_name = wanted.name if wanted is not None else query.vehicle.strip()
        wanted_lineage = wanted.lineage if wanted is not None else None

        # One pass over the catalog, not one lookup per row: a catalog backed
        # by a table would otherwise be queried once for every historical row.
        lineages = _lineages_by_written_name(self.vehicle_catalog)

        candidates = [
            record
            for record in (
                *self.source.dataset_operations(query.vehicle_category),
                *self.source.recorded_operations(query.vehicle_category),
            )
            if record.operation_id != query.exclude_operation_id
        ]
        ranked = sorted(
            (_score(record, query, wanted_name, wanted_lineage, lineages) for record in candidates),
            key=_rank_key,
        )
        return tuple(ranked[: query.limit])


def _lineages_by_written_name(catalog: VehicleCatalog) -> dict[str, VehicleLineage]:
    lineages: dict[str, VehicleLineage] = {}
    for option in catalog.options():
        if not option.group:
            continue
        for name in (option.name, *option.aliases):
            lineages.setdefault(_vehicle_key(name), option.lineage)
    return lineages


def _refines(lineage: VehicleLineage) -> bool:
    return lineage.type != lineage.group


def _vehicle_key(name: str) -> str:
    # The same normalisation the catalogs use for `find`.
    return name.strip().casefold().replace(" ", "")


def _score(
    record: HistoricalOperationRecord,
    query: SimilarOperationsQuery,
    wanted_name: str,
    wanted_lineage: VehicleLineage | None,
    lineages: dict[str, VehicleLineage],
) -> SimilarOperation:
    lineage = lineages.get(_vehicle_key(record.vehicle)) if record.vehicle else None
    same_group = same_type = False
    if wanted_lineage is not None and lineage is not None:
        same_group = lineage.group == wanted_lineage.group
        # Same type is only meaningful inside the same group (two groups may
        # name a type alike), and only when the type is a real refinement: a
        # group with a single type would otherwise label every group match a
        # type match and tell the planner nothing new.
        same_type = same_group and _refines(wanted_lineage) and lineage.type == wanted_lineage.type
    if record.vehicle is not None and record.vehicle == wanted_name:
        vehicle_match = VehicleMatch.SAME
    elif same_type:
        vehicle_match = VehicleMatch.SAME_TYPE
    elif same_group:
        vehicle_match = VehicleMatch.SAME_GROUP
    else:
        # Includes rows with no vehicle recorded: an unnamed row can be the
        # same crane, but nothing in it says so, and pretending otherwise
        # would rank it above rows that are known to be that crane.
        vehicle_match = VehicleMatch.SAME_CATEGORY

    same_mode = None if query.activity_mode is None else record.activity_mode == query.activity_mode
    distance_delta = (
        None
        if query.total_distance_km is None
        else record.total_distance_km - query.total_distance_km
    )
    lifting_delta = (
        None if query.lifting_hours is None else (record.lifting_hours or 0.0) - query.lifting_hours
    )
    score = 0.0
    if distance_delta is not None:
        score += abs(distance_delta) / max(query.total_distance_km or 0.0, 1.0)
    if lifting_delta is not None:
        score += abs(lifting_delta) / max(query.lifting_hours or 0.0, 1.0)
    return SimilarOperation(
        record=record,
        vehicle_type=lineage.type if lineage is not None else None,
        vehicle_group=lineage.group if lineage is not None else None,
        match=SimilarityMatch(
            vehicle=vehicle_match,
            activity_mode=same_mode,
            distance_delta_km=distance_delta,
            lifting_hours_delta=lifting_delta,
            score=round(score, 4),
        ),
    )


_VEHICLE_TIER = {
    VehicleMatch.SAME: 0,
    VehicleMatch.SAME_TYPE: 1,
    VehicleMatch.SAME_GROUP: 2,
    VehicleMatch.SAME_CATEGORY: 3,
}


def _rank_key(item: SimilarOperation) -> tuple[int, int, float, float, str]:
    match = item.match
    # Newest first among equals; a row with no timestamp (dataset rows) sorts
    # after one that has one, which is the honest order for "most recent".
    recency = -item.record.recorded_at.timestamp() if item.record.recorded_at else 0.0
    return (
        _VEHICLE_TIER[match.vehicle],
        0 if match.activity_mode in (True, None) else 1,
        match.score,
        recency,
        item.record.operation_id,
    )
