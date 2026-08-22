"""Loading real model artefacts (ADR 0009 trusted formats, ADR 0010 step 1).

Uses genuinely trained scikit-learn models serialised with skops rather than
stubs: the point of this layer is that a real artefact round-trips and
answers correctly, which a fake predictor cannot demonstrate.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import skops.io as skops_io
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer

from fuel_predictor.application.model_activation import LoadedModel
from fuel_predictor.domain.model_activation import ModelLoadFailedError
from fuel_predictor.domain.model_package import (
    FeatureSchemaEntry,
    ManifestMetrics,
    ModelFormat,
    ModelPackageManifest,
    TargetDefinition,
)
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion
from fuel_predictor.infrastructure.model_artifact_loader import (
    ModelPackageArtifactLoader,
    build_loader,
)


def _manifest(model_format: ModelFormat = ModelFormat.SKOPS) -> ModelPackageManifest:
    return ModelPackageManifest(
        model_version="fuel-model-test",
        model_format=model_format,
        runtime_compatibility_version="skops-0.11",
        target=TargetDefinition(name="prepared_fuel_liters", unit="liters"),
        feature_contract_version="numeric-v1",
        feature_schema=(
            FeatureSchemaEntry(name="total_distance_km", type="number"),
            FeatureSchemaEntry(name="lifting_hours", type="number"),
        ),
        training_dataset_version="DSV-000001",
        trained_at=datetime(2026, 8, 22, tzinfo=UTC),
        source_revision="abc123",
        overall_metrics=ManifestMetrics(3.0, 4.0, 12.0, 90.0),
        category_metrics=(),
        test_set_size=50,
        model_size_bytes=1000,
        expected_memory_bytes=10_000_000,
        package_checksums={},
    )


def _version() -> ModelVersion:
    return ModelVersion(
        model_version_id="MDL-TEST",
        version=1,
        dataset_version_id="DSV-000001",
        feature_version="numeric-v1",
        algorithm="linear_regression",
        artifact_uri="memory://test",
        trained_at=datetime(2026, 8, 22, tzinfo=UTC),
        training_row_count=20,
        uncertainty_liters=2.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )


def _trained_skops_bytes() -> bytes:
    """A genuinely fitted model: fuel = 0.5 * distance + 2 * lifting_hours."""
    rows = [[distance, lifting] for distance in (10, 20, 30, 40) for lifting in (0, 1, 2)]
    targets = [0.5 * distance + 2.0 * lifting for distance, lifting in rows]
    model = LinearRegression().fit(rows, targets)
    return bytes(skops_io.dumps(model))


def _trusted_types(payload: bytes) -> list[str]:
    return list(skops_io.get_untrusted_types(data=payload))


def test_a_real_skops_model_loads_and_predicts_correctly() -> None:
    payload = _trained_skops_bytes()
    loader = ModelPackageArtifactLoader(
        manifest=_manifest(),
        artifact_bytes=payload,
        trusted_skops_types=tuple(_trusted_types(payload)),
    )

    loaded = loader.load(_version())

    assert isinstance(loaded, LoadedModel)
    assert loaded.version.model_version_id == "MDL-TEST"
    # 0.5 * 30 + 2 * 1 = 17
    assert loaded.predict({"total_distance_km": 30.0, "lifting_hours": 1.0}) == pytest.approx(
        17.0, abs=1e-6
    )


def test_features_are_fed_in_the_manifest_declared_order() -> None:
    """Order matters: swapping two numeric features silently changes the answer.

    Asserted with an asymmetric case, so a loader that ignored declared order
    would produce a different number rather than coincidentally the same one.
    """
    payload = _trained_skops_bytes()
    loader = ModelPackageArtifactLoader(
        manifest=_manifest(),
        artifact_bytes=payload,
        trusted_skops_types=tuple(_trusted_types(payload)),
    )
    loaded = loader.load(_version())

    # 0.5 * 40 + 2 * 0 = 20, whereas the reversed order would give 0.5*0 + 2*40 = 80
    assert loaded.predict({"total_distance_km": 40.0, "lifting_hours": 0.0}) == pytest.approx(
        20.0, abs=1e-6
    )


def _untrusted_skops_bytes() -> bytes:
    """An artefact carrying a user-defined callable, which skops will not trust.

    Plain scikit-learn estimators are all on skops' own trusted list, so a
    package containing only those has nothing to refuse — the interesting
    case is code the package brought with it.
    """
    pipeline = make_pipeline(
        FunctionTransformer(_package_supplied_transform), LinearRegression()
    ).fit([[10.0, 0.0], [20.0, 1.0]], [5.0, 12.0])
    return bytes(skops_io.dumps(pipeline))


def _package_supplied_transform(values: Any) -> Any:
    return values


def test_an_untrusted_type_is_refused_rather_than_reconstructed() -> None:
    """skops refuses unknown types by default; that refusal must not be bypassed.

    This is the security property ADR 0009 depends on — a package must not be
    able to make production reconstruct arbitrary objects it brought along.
    """
    payload = _untrusted_skops_bytes()
    assert _trusted_types(payload), "fixture must actually contain an untrusted type"

    loader = ModelPackageArtifactLoader(
        manifest=_manifest(),
        artifact_bytes=payload,
        trusted_skops_types=(),  # nothing allowed
    )

    with pytest.raises(ModelLoadFailedError) as excinfo:
        loader.load(_version())

    assert "tidak dipercaya" in str(excinfo.value)


def test_an_explicitly_allowed_type_loads() -> None:
    """The allow-list is a deliberate decision, so it must actually work."""
    payload = _untrusted_skops_bytes()

    loader = ModelPackageArtifactLoader(
        manifest=_manifest(),
        artifact_bytes=payload,
        trusted_skops_types=tuple(_trusted_types(payload)),
    )

    assert loader.load(_version()) is not None


def test_corrupt_artefact_bytes_fail_as_a_load_error_not_a_crash() -> None:
    loader = ModelPackageArtifactLoader(
        manifest=_manifest(),
        artifact_bytes=b"this is not a model",
        trusted_skops_types=(),
    )

    with pytest.raises(ModelLoadFailedError):
        loader.load(_version())


def test_build_loader_requires_the_artefact_the_manifest_declares() -> None:
    with pytest.raises(ModelLoadFailedError) as excinfo:
        build_loader(_manifest(), members={"manifest.json": b"{}"})

    assert "model.skops" in str(excinfo.value)


def test_build_loader_selects_the_member_matching_the_declared_format() -> None:
    payload = _trained_skops_bytes()

    loader = build_loader(
        _manifest(),
        members={"model.skops": payload, "manifest.json": b"{}"},
        trusted_skops_types=_trusted_types(payload),
    )

    assert loader.artifact_bytes == payload


def test_an_onnx_manifest_looks_for_the_onnx_member() -> None:
    with pytest.raises(ModelLoadFailedError) as excinfo:
        build_loader(_manifest(ModelFormat.ONNX), members={"model.skops": b"wrong format"})

    assert "model.onnx" in str(excinfo.value)


def test_a_model_returning_more_than_one_value_per_row_is_refused() -> None:
    """A multi-output model does not fit the single-estimate contract."""

    class _MultiOutput:
        def predict(self, rows: Any) -> list[list[float]]:
            return [[1.0, 2.0]]

    loaded = LoadedModel(version=_version(), predictor=_MultiOutputPredictor(_MultiOutput()))

    with pytest.raises(ModelLoadFailedError):
        loaded.predict({"total_distance_km": 1.0, "lifting_hours": 0.0})


class _MultiOutputPredictor:
    def __init__(self, estimator: Any) -> None:
        self.estimator = estimator

    def predict(self, features: Any) -> float:
        from fuel_predictor.infrastructure.model_artifact_loader import _single_number

        return _single_number(self.estimator.predict([[0]]))
