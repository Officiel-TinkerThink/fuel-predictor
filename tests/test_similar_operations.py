"""Ranking past operations by how much they resemble the one being planned.

The order is what the agent will explain to the planner, so it is pinned here:
the same unit first, then the same kind of machine, then anything in the
category; within that, the same activity; within that, the nearest distance.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from fuel_predictor.application.similar_operations import (
    FindSimilarOperations,
    HistoricalOperationRecord,
    HistorySource,
    SimilarOperation,
    SimilarOperationsQuery,
    VehicleMatch,
)
from fuel_predictor.application.vehicles import VehicleOption
from fuel_predictor.domain.daily_operation import ActivityMode, DistanceSource, VehicleCategory


class _Fleet:
    def __init__(self, *options: VehicleOption) -> None:
        self._options = options

    def options(self) -> tuple[VehicleOption, ...]:
        return self._options

    def find(self, name: str) -> VehicleOption | None:
        wanted = name.strip().casefold().replace(" ", "")
        for option in self._options:
            spellings = (option.name, *option.aliases)
            if wanted in {spelling.casefold().replace(" ", "") for spelling in spellings}:
                return option
        return None


class _History:
    def __init__(
        self,
        dataset: Sequence[HistoricalOperationRecord] = (),
        recorded: Sequence[HistoricalOperationRecord] = (),
    ) -> None:
        self._dataset = tuple(dataset)
        self._recorded = tuple(recorded)

    def dataset_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        return self._dataset

    def recorded_operations(
        self, vehicle_category: VehicleCategory
    ) -> tuple[HistoricalOperationRecord, ...]:
        return self._recorded


_FLEET = _Fleet(
    VehicleOption("Truck Crane 01", "Crane", ("T CRANE 01",)),
    VehicleOption("Truck Crane 02", "Crane", ()),
    VehicleOption("Prime Mover", "Truck", ()),
)


def _row(
    operation_id: str,
    vehicle: str | None,
    distance: float,
    mode: ActivityMode = ActivityMode.TRANSPORT,
    lifting_hours: float | None = None,
    source: HistorySource = HistorySource.DATASET,
    recorded_at: datetime | None = None,
) -> HistoricalOperationRecord:
    return HistoricalOperationRecord(
        source=source,
        operation_id=operation_id,
        vehicle=vehicle,
        vehicle_category=VehicleCategory.ANGBER,
        activity_mode=mode,
        lifting_hours=lifting_hours,
        total_distance_km=distance,
        distance_source=DistanceSource.MANUAL,
        prepared_fuel_liters=20.0 if source is HistorySource.DATASET else None,
        recorded_at=recorded_at,
    )


def _ids(results: Sequence[SimilarOperation]) -> list[str]:
    return [item.record.operation_id for item in results]


def test_the_same_vehicle_outranks_the_same_kind_of_machine_which_outranks_the_category() -> None:
    history = _History(
        dataset=[
            _row("truck", "Prime Mover", 30),
            _row("other-crane", "Truck Crane 02", 30),
            _row("this-crane", "Truck Crane 01", 30),
            _row("unnamed", None, 30),
        ]
    )
    results = FindSimilarOperations(history, _FLEET).execute(
        SimilarOperationsQuery(vehicle="truck crane 01", total_distance_km=30)
    )

    assert _ids(results) == ["this-crane", "other-crane", "truck", "unnamed"]
    assert [item.match.vehicle for item in results] == [
        VehicleMatch.SAME,
        VehicleMatch.SAME_GROUP,
        VehicleMatch.SAME_CATEGORY,
        VehicleMatch.SAME_CATEGORY,
    ]


def test_within_a_tier_the_same_activity_then_the_nearest_distance_wins() -> None:
    history = _History(
        dataset=[
            _row("far", "Truck Crane 01", 80),
            _row("lifting-near", "Truck Crane 01", 31, ActivityMode.LIFTING, 2),
            _row("near", "Truck Crane 01", 33),
            _row("exact", "Truck Crane 01", 30),
        ]
    )
    results = FindSimilarOperations(history, _FLEET).execute(
        SimilarOperationsQuery(
            vehicle="Truck Crane 01", activity_mode=ActivityMode.TRANSPORT, total_distance_km=30
        )
    )

    assert _ids(results) == ["exact", "near", "far", "lifting-near"]
    assert results[0].match.activity_mode is True
    assert results[0].match.distance_delta_km == 0
    assert results[1].match.distance_delta_km == 3
    assert results[-1].match.activity_mode is False


def test_a_row_with_no_vehicle_never_outranks_one_known_to_be_the_unit() -> None:
    history = _History(
        dataset=[_row("unnamed-exact", None, 30), _row("named-far", "Truck Crane 01", 60)]
    )
    results = FindSimilarOperations(history, _FLEET).execute(
        SimilarOperationsQuery(vehicle="Truck Crane 01", total_distance_km=30)
    )

    assert _ids(results) == ["named-far", "unnamed-exact"]


def test_recorded_and_dataset_rows_are_merged_and_the_newest_breaks_ties() -> None:
    history = _History(
        dataset=[_row("sheet", "Truck Crane 01", 30)],
        recorded=[
            _row(
                "older",
                "Truck Crane 01",
                30,
                source=HistorySource.RECORDED,
                recorded_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            _row(
                "newer",
                "Truck Crane 01",
                30,
                source=HistorySource.RECORDED,
                recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ],
    )
    results = FindSimilarOperations(history, _FLEET).execute(
        SimilarOperationsQuery(vehicle="Truck Crane 01", total_distance_km=30)
    )

    assert _ids(results) == ["newer", "older", "sheet"]


def test_the_limit_is_respected_and_an_empty_history_is_empty() -> None:
    history = _History(dataset=[_row(f"row-{n}", "Truck Crane 01", 30 + n) for n in range(10)])
    finder = FindSimilarOperations(history, _FLEET)

    assert len(finder.execute(SimilarOperationsQuery(vehicle="Truck Crane 01", limit=3))) == 3
    assert finder.execute(SimilarOperationsQuery(vehicle="Truck Crane 01", limit=0)) == ()
    assert (
        FindSimilarOperations(_History(), _FLEET).execute(
            SimilarOperationsQuery(vehicle="Truck Crane 01")
        )
        == ()
    )


def test_lifting_hours_count_toward_the_distance_score() -> None:
    history = _History(
        dataset=[
            _row("two-hours", "Truck Crane 01", 30, ActivityMode.LIFTING, 2),
            _row("five-hours", "Truck Crane 01", 30, ActivityMode.LIFTING, 5),
        ]
    )
    results = FindSimilarOperations(history, _FLEET).execute(
        SimilarOperationsQuery(
            vehicle="Truck Crane 01",
            activity_mode=ActivityMode.LIFTING,
            lifting_hours=2.5,
            total_distance_km=30,
        )
    )

    assert _ids(results) == ["two-hours", "five-hours"]
    assert results[0].match.lifting_hours_delta == -0.5
