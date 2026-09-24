"""The post-activation health check asks the model in the current feature contract.

It used to be a hand-written dict from baseline-v1. When `vehicle` became a
feature (baseline-v2) the dict was not updated, so a package that actually
reads the vehicle - every model trained under the contract production serves -
was activated and then reported as failing its health check.
"""

from fuel_predictor.application.model_activation import answers_a_representative_case
from fuel_predictor.application.prediction_features import feature_values
from fuel_predictor.application.vehicles import VehicleLineage
from fuel_predictor.domain.daily_operation import (
    ActivityMode,
    DailyOperation,
    DistanceSource,
    VehicleCategory,
)
from fuel_predictor.main import HEALTH_CHECK_FEATURES


def test_the_health_check_case_carries_every_feature_of_the_contract() -> None:
    contract = feature_values(
        DailyOperation(
            operation_id="OPR-X",
            vehicle_category=VehicleCategory.ANGBER,
            vehicle="VT 01",
            activity_mode=ActivityMode.TRANSPORT,
            lifting_hours=None,
            total_distance_km=10,
            distance_source=DistanceSource.MANUAL,
        ),
        VehicleLineage.unknown(),
    )

    assert set(HEALTH_CHECK_FEATURES) == set(contract)


class _ReadsTheVehicle:
    """A model that, like any baseline-v2 model, looks the vehicle up."""

    def predict(self, features: dict[str, str | float]) -> float:
        return 10.0 if features["vehicle"] else 0.0


def test_a_model_that_reads_the_vehicle_passes_the_health_check() -> None:
    check = answers_a_representative_case(HEALTH_CHECK_FEATURES)

    assert check(_ReadsTheVehicle()) is None  # type: ignore[arg-type]
