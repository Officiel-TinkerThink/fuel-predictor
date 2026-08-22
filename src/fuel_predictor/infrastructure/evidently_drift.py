from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from evidently import DataDefinition, Dataset, Report  # type: ignore[import-untyped]
from evidently.presets import DataDriftPreset  # type: ignore[import-untyped]

from fuel_predictor.application.monitoring import FeatureDriftAnalyzer
from fuel_predictor.domain.monitoring import FeatureDriftSummary


class EvidentlyFeatureDriftAnalyzer(FeatureDriftAnalyzer):
    """Runs Evidently locally; no report is sent to a hosted service."""

    _minimum_row_count = 20

    def analyze(
        self,
        reference_rows: Sequence[dict[str, str | float]],
        current_rows: Sequence[dict[str, str | float]],
        drift_share_threshold: float,
    ) -> FeatureDriftSummary:
        if (
            len(reference_rows) < self._minimum_row_count
            or len(current_rows) < self._minimum_row_count
        ):
            return FeatureDriftSummary(
                len(reference_rows),
                len(current_rows),
                "insufficient_data",
                None,
                drift_share_threshold,
                (),
            )
        definition = DataDefinition(
            numerical_columns=["total_distance_km", "lifting_hours"],
            categorical_columns=["vehicle_category", "activity_mode", "distance_source"],
        )
        reference_data = Dataset.from_pandas(
            pd.DataFrame(reference_rows), data_definition=definition
        )
        current_data = Dataset.from_pandas(pd.DataFrame(current_rows), data_definition=definition)
        report = Report([DataDriftPreset(drift_share=drift_share_threshold)])
        snapshot = report.run(current_data=current_data, reference_data=reference_data)
        result = _snapshot_mapping(snapshot)
        drift_share, drifting_features = _drift_results(result)
        return FeatureDriftSummary(
            len(reference_rows),
            len(current_rows),
            "ready",
            drift_share,
            drift_share_threshold,
            drifting_features,
        )


def _snapshot_mapping(snapshot: Any) -> Mapping[str, Any]:
    for name in ("dict", "as_dict"):
        converter = getattr(snapshot, name, None)
        if callable(converter):
            result = converter()
            if isinstance(result, Mapping):
                return result
    return {}


def _drift_results(result: Mapping[str, Any]) -> tuple[float, tuple[str, ...]]:
    drift_share = 0.0
    drifting_features: list[str] = []
    metrics = result.get("metrics")
    if not isinstance(metrics, list):
        return drift_share, ()
    for metric in metrics:
        if not isinstance(metric, Mapping):
            continue
        metric_name = metric.get("metric_name")
        value = metric.get("value")
        config = metric.get("config")
        if (
            isinstance(metric_name, str)
            and metric_name.startswith("DriftedColumnsCount")
            and isinstance(value, Mapping)
            and isinstance(value.get("share"), (int, float))
        ):
            drift_share = float(value["share"])
        if (
            isinstance(metric_name, str)
            and metric_name.startswith("ValueDrift")
            and isinstance(config, Mapping)
            and isinstance(config.get("column"), str)
            and isinstance(config.get("threshold"), (int, float))
            and isinstance(value, (int, float))
            and "p_value" in metric_name
            and value < config["threshold"]
        ):
            drifting_features.append(config["column"])
    return drift_share, tuple(sorted(drifting_features))
