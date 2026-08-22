from collections.abc import Sequence
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient
from sklearn.feature_extraction import DictVectorizer  # type: ignore[import-untyped]
from sklearn.linear_model import LinearRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]

from fuel_predictor.application.baseline_predictions import BaselineModelStore
from fuel_predictor.application.prediction_features import FEATURE_VERSION, feature_values
from fuel_predictor.domain.historical_dataset import HistoricalDailyOperation


class MlflowBaselineModelStore(BaselineModelStore):
    """Local MLflow-backed artifacts; model DB records remain the serving lineage."""

    def __init__(self, tracking_uri: str, artifact_location: str | None = None) -> None:
        self._tracking_uri = tracking_uri
        self._artifact_location = artifact_location

    @classmethod
    def local(cls, tracking_directory: Path) -> "MlflowBaselineModelStore":
        """Local file-backed store for single-process/non-Docker development."""
        root = tracking_directory.resolve()
        tracking_uri = f"sqlite:///{(root / 'mlflow.db').as_posix()}"
        artifact_location = (root / "artifacts").as_uri()
        return cls(tracking_uri, artifact_location)

    def train(
        self, model_version_id: str, operations: Sequence[HistoricalDailyOperation]
    ) -> tuple[str, float]:
        features = [feature_values(item.operation) for item in operations]
        labels = np.asarray([item.prepared_fuel_liters for item in operations])
        pipeline = Pipeline(
            [("features", DictVectorizer(sparse=False)), ("regression", LinearRegression())]
        )
        pipeline.fit(features, labels)
        residuals = np.abs(labels - pipeline.predict(features))
        uncertainty = max(1.0, float(np.quantile(residuals, 0.9)))
        mlflow.set_tracking_uri(self._tracking_uri)
        client = MlflowClient(tracking_uri=self._tracking_uri)
        experiment = client.get_experiment_by_name("fuel-predictor-baselines")
        if experiment is None:
            # A remote tracking server (self._artifact_location is None) picks its own
            # artifact root; only a local file-backed store needs one supplied here.
            client.create_experiment(
                "fuel-predictor-baselines", artifact_location=self._artifact_location
            )
        mlflow.set_experiment("fuel-predictor-baselines")
        with mlflow.start_run(run_name=model_version_id) as run:
            mlflow.log_params(
                {
                    "algorithm": "linear_regression",
                    "feature_version": FEATURE_VERSION,
                    "training_row_count": len(operations),
                }
            )
            mlflow.log_metric("training_residual_p90_liters", uncertainty)
            mlflow.sklearn.log_model(pipeline, artifact_path="model")
            return f"runs:/{run.info.run_id}/model", uncertainty

    def predict(self, artifact_uri: str, features: dict[str, str | float]) -> float:
        mlflow.set_tracking_uri(self._tracking_uri)
        pipeline = mlflow.sklearn.load_model(artifact_uri)
        return float(pipeline.predict([features])[0])
