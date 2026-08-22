"""Loading a validated model package's artefact (ADR 0009, ADR 0010 step 1).

Only the two trusted formats are loadable, and neither executes arbitrary
code on load — that is the whole reason ADR 0009 restricts the format set.
The loader never inspects a path supplied by the package; it is handed bytes
that archive handling already validated and checksummed.

`onnxruntime` and `skops` are imported lazily inside the functions that need
them rather than at module scope. Importing `skops.io` pulls in
scikit-learn's estimator discovery, which walks loaded shared libraries and
can fail outright on some Windows hosts — and it is slow. Serving a
prediction page should not pay that cost, and the application must not fail
to start on a machine that never uploads a package.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy

from fuel_predictor.application.model_activation import LoadedModel
from fuel_predictor.domain.model_activation import ModelLoadFailedError
from fuel_predictor.domain.model_package import ModelFormat, ModelPackageManifest
from fuel_predictor.domain.prediction import ModelVersion


@dataclass(frozen=True, slots=True)
class OnnxPredictor:
    """Wraps an ONNX session behind the same `predict` shape everything else uses."""

    session: Any
    feature_order: tuple[str, ...]

    def predict(self, features: Mapping[str, str | float | bool]) -> float:
        inputs = _onnx_inputs(self.session, features, self.feature_order)
        outputs = self.session.run(None, inputs)
        return _single_number(outputs[0])


@dataclass(frozen=True, slots=True)
class SkopsPredictor:
    estimator: Any
    feature_order: tuple[str, ...]

    def predict(self, features: Mapping[str, str | float | bool]) -> float:
        row = [[features[name] for name in self.feature_order]]
        return _single_number(self.estimator.predict(row))


@dataclass(frozen=True, slots=True)
class ModelPackageArtifactLoader:
    """Loads and warms the artefact for one validated package.

    `trusted_skops_types` is an explicit allow-list. `skops` refuses unknown
    types by default precisely so an untrusted file cannot reconstruct
    arbitrary objects; widening this list is a security decision, not a
    convenience, so it is configuration rather than something inferred from
    whatever the file happens to contain.
    """

    manifest: ModelPackageManifest
    artifact_bytes: bytes
    trusted_skops_types: tuple[str, ...] = ()

    def load(self, version: ModelVersion) -> LoadedModel:
        try:
            predictor = self._build_predictor()
        except ModelLoadFailedError:
            raise
        except Exception as error:  # noqa: BLE001 - surfaced as a domain failure
            raise ModelLoadFailedError(f"{type(error).__name__}: {error}") from error

        loaded = LoadedModel(version=version, predictor=predictor)
        self._warm(loaded)
        return loaded

    def _build_predictor(self) -> OnnxPredictor | SkopsPredictor:
        order = self.manifest.feature_names_in_order()
        if self.manifest.model_format is ModelFormat.ONNX:
            import onnxruntime  # type: ignore[import-untyped]

            session = onnxruntime.InferenceSession(
                self.artifact_bytes,
                providers=["CPUExecutionProvider"],
            )
            return OnnxPredictor(session=session, feature_order=order)

        import skops.io as skops_io  # type: ignore[import-untyped]

        unknown = skops_io.get_untrusted_types(data=self.artifact_bytes)
        disallowed = sorted(set(unknown) - set(self.trusted_skops_types))
        if disallowed:
            raise ModelLoadFailedError(
                "Paket memuat tipe yang tidak dipercaya: " + ", ".join(disallowed)
            )
        estimator = skops_io.loads(self.artifact_bytes, trusted=list(self.trusted_skops_types))
        return SkopsPredictor(estimator=estimator, feature_order=order)

    def _warm(self, loaded: LoadedModel) -> None:
        """Run one throwaway inference so the first real request isn't the slow one.

        Failure here is a load failure: a model that cannot answer a
        well-formed request is not usable, and finding that out now keeps the
        currently-active model serving (ADR 0010).
        """
        sample = {
            entry.name: _neutral_value(entry.type) for entry in self.manifest.feature_schema
        }
        try:
            loaded.predict(sample)
        except Exception as error:  # noqa: BLE001 - surfaced as a domain failure
            raise ModelLoadFailedError(
                f"Model gagal saat pemanasan: {type(error).__name__}: {error}"
            ) from error


def _neutral_value(feature_type: str) -> str | float | bool:
    if feature_type == "number":
        return 0.0
    if feature_type == "boolean":
        return False
    return ""


def _onnx_inputs(
    session: Any,
    features: Mapping[str, str | float | bool],
    feature_order: tuple[str, ...],
) -> dict[str, Any]:
    """Map feature values onto the session's declared inputs.

    Handles both shapes a converted scikit-learn pipeline can take: a single
    combined tensor, or one named input per feature (what
    `skl2onnx` emits for a mixed-type pipeline).
    """
    declared = session.get_inputs()
    if len(declared) == 1 and declared[0].name not in feature_order:
        row = [[features[name] for name in feature_order]]
        return {declared[0].name: numpy.array(row, dtype=numpy.float32)}

    inputs: dict[str, Any] = {}
    for spec in declared:
        value = features[spec.name]
        if isinstance(value, str):
            inputs[spec.name] = numpy.array([[value]], dtype=object)
        else:
            inputs[spec.name] = numpy.array([[float(value)]], dtype=numpy.float32)
    return inputs


def _single_number(output: Any) -> float:
    """Reduce whatever shape a runtime returns to one number.

    ONNX and scikit-learn both return arrays even for a single-row
    prediction, and the nesting differs between them.
    """
    array = numpy.asarray(output).reshape(-1)
    if array.size != 1:
        raise ModelLoadFailedError(
            f"Model mengembalikan {array.size} nilai untuk satu baris; diharapkan tepat satu."
        )
    return float(array[0])


def build_loader(
    manifest: ModelPackageManifest,
    members: Mapping[str, bytes],
    trusted_skops_types: Sequence[str] = (),
) -> ModelPackageArtifactLoader:
    """Pick the artefact member matching the manifest's declared format."""
    filename = "model.onnx" if manifest.model_format is ModelFormat.ONNX else "model.skops"
    if filename not in members:
        raise ModelLoadFailedError(f"Paket tidak memuat berkas artefak '{filename}'.")
    return ModelPackageArtifactLoader(
        manifest=manifest,
        artifact_bytes=members[filename],
        trusted_skops_types=tuple(trusted_skops_types),
    )
