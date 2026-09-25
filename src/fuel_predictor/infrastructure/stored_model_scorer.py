"""Scores any stored model version by its artifact URI, whatever produced it.

A model trained in this process lives in MLflow (ADR 0011); a model trained
outside arrives as a package and is retained on disk (ADR 0009, ADR 0010).
Serving the active model normally goes through the resident holder, but two
paths reach a model by its artifact URI instead: prediction right after a
restart, before anything is resident, and the evaluations that re-score every
recorded actual (model management, candidate comparison). Those used the
MLflow store alone, which cannot open a package - so an active package
stopped predicting after every restart, and the model pages failed once an
actual was recorded.

A retained package is loaded from its own bytes, re-verified against its
manifest's checksums, the same way activation loads it. Each model is loaded
once and kept: the evaluations ask the same model about every actual.
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fuel_predictor.application.model_activation import LoadedModel
from fuel_predictor.application.model_package_ingestion import (
    ParseModelPackageManifest,
    verify_member_checksums,
)
from fuel_predictor.application.model_package_validation import json_member
from fuel_predictor.domain.historical_dataset import HistoricalDailyOperation
from fuel_predictor.domain.model_package import ModelPackageManifest
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion


class _TrainingStore(Protocol):
    def train(
        self, model_version_id: str, operations: Sequence[HistoricalDailyOperation]
    ) -> tuple[str, float]: ...

    def predict(self, artifact_uri: str, features: dict[str, str | float]) -> float: ...


class _RetainedPackages(Protocol):
    def exists(self, model_version: str) -> bool: ...

    def read_members(self, model_version: str) -> dict[str, bytes]: ...


class _ArtifactLoader(Protocol):
    def load(self, version: ModelVersion) -> LoadedModel: ...


_Predict = Callable[[dict[str, str | float]], float]


class StoredModelScorer:
    """`BaselineModelStore` for the serving and evaluation paths."""

    def __init__(
        self,
        training_store: _TrainingStore,
        packages: _RetainedPackages,
        parse_manifest: ParseModelPackageManifest,
        build_artifact_loader: Callable[
            [ModelPackageManifest, Mapping[str, bytes]], _ArtifactLoader
        ],
    ) -> None:
        self._training_store = training_store
        self._packages = packages
        self._parse_manifest = parse_manifest
        self._build_artifact_loader = build_artifact_loader
        self._loaded: dict[str, _Predict] = {}
        self._lock = threading.Lock()

    def train(
        self, model_version_id: str, operations: Sequence[HistoricalDailyOperation]
    ) -> tuple[str, float]:
        return self._training_store.train(model_version_id, operations)

    def predict(self, artifact_uri: str, features: dict[str, str | float]) -> float:
        return self._predictor(artifact_uri)(features)

    def _predictor(self, artifact_uri: str) -> _Predict:
        with self._lock:
            cached = self._loaded.get(artifact_uri)
        if cached is not None:
            return cached
        package = self._retained_package(artifact_uri)
        predictor: _Predict
        if package is None:

            def predictor(features: dict[str, str | float]) -> float:
                return self._training_store.predict(artifact_uri, features)
        else:
            predictor = self._load_package(package)
        with self._lock:
            self._loaded.setdefault(artifact_uri, predictor)
            return self._loaded[artifact_uri]

    def _retained_package(self, artifact_uri: str) -> str | None:
        """The package's version name when this URI is a retained package's
        directory; None for an MLflow URI (runs:/…, file:…)."""
        path = Path(artifact_uri)
        if not path.is_dir():
            return None
        return path.name if self._packages.exists(path.name) else None

    def _load_package(self, model_version: str) -> _Predict:
        members = self._packages.read_members(model_version)
        manifest = self._parse_manifest.execute(json_member(members, "manifest.json"))
        verify_member_checksums(members, manifest.package_checksums)
        loaded = self._build_artifact_loader(manifest, members).load(_scoring_identity(manifest))
        return loaded.predict


def _scoring_identity(manifest: ModelPackageManifest) -> ModelVersion:
    """The loader wants a version to attach to what it loads. The real one
    lives in the database; scoring only needs the numbers."""
    return ModelVersion(
        model_version_id=manifest.model_version,
        version=0,
        dataset_version_id=manifest.training_dataset_version,
        feature_version=manifest.feature_contract_version,
        algorithm="(penilaian)",
        artifact_uri="memory://scoring",
        trained_at=datetime.now(UTC),
        training_row_count=0,
        uncertainty_liters=manifest.overall_metrics.mae,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )
