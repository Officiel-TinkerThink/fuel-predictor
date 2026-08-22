"""Builds a conforming model package (ADR 0009).

Lives in this repository rather than the training environment so the package
contract has exactly one implementation. A packager maintained separately
would drift from the validator, and the failure mode of that drift is
packages that are rejected in production for reasons the trainer cannot
reproduce.

This module is imported by the external training environment; it is not part
of the serving path.
"""

import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from typing import Any

_MANIFEST = "manifest.json"
_REFERENCE_STATISTICS = "reference-statistics.json"
_SMOKE_TESTS = "smoke-tests.json"


@dataclass(frozen=True, slots=True)
class PackagingError(ValueError):
    """The caller asked for a package that could not be built correctly."""

    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ModelPackageBuilder:
    """Assembles the archive and fills in everything derivable.

    Checksums, `model_size_bytes`, and the member list are computed here
    rather than accepted from the caller: they are facts about the bytes
    being written, and a caller that could state them separately could state
    them wrongly.
    """

    model_version: str
    model_format: str
    runtime_compatibility_version: str
    feature_contract_version: str
    feature_schema: Sequence[Mapping[str, str]]
    target_name: str
    target_unit: str
    training_dataset_version: str
    trained_at: datetime
    source_revision: str
    metrics: Mapping[str, Any]
    test_set_size: int
    expected_memory_bytes: int

    def build(
        self,
        model_bytes: bytes,
        reference_statistics: Mapping[str, Any],
        smoke_tests: Mapping[str, Any],
    ) -> bytes:
        self._reject_obvious_mistakes(model_bytes, smoke_tests)

        artefact_name = "model.onnx" if self.model_format == "onnx" else "model.skops"
        statistics_bytes = _canonical_json(reference_statistics)
        smoke_bytes = _canonical_json(smoke_tests)

        manifest = {
            "model_version": self.model_version,
            "model_format": self.model_format,
            "runtime_compatibility_version": self.runtime_compatibility_version,
            "target": {"name": self.target_name, "unit": self.target_unit},
            "feature_contract_version": self.feature_contract_version,
            "feature_schema": [dict(entry) for entry in self.feature_schema],
            "training_dataset_version": self.training_dataset_version,
            "trained_at": self.trained_at.isoformat(),
            "source_revision": self.source_revision,
            "metrics": _plain(self.metrics),
            "test_set_size": self.test_set_size,
            "model_size_bytes": len(model_bytes),
            "expected_memory_bytes": self.expected_memory_bytes,
            # manifest.json is absent by design: it cannot carry a checksum of
            # the bytes that contain that checksum.
            "package_checksums": {
                artefact_name: sha256(model_bytes).hexdigest(),
                _REFERENCE_STATISTICS: sha256(statistics_bytes).hexdigest(),
                _SMOKE_TESTS: sha256(smoke_bytes).hexdigest(),
            },
        }

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(_MANIFEST, _canonical_json(manifest))
            archive.writestr(artefact_name, model_bytes)
            archive.writestr(_REFERENCE_STATISTICS, statistics_bytes)
            archive.writestr(_SMOKE_TESTS, smoke_bytes)
        return buffer.getvalue()

    def _reject_obvious_mistakes(
        self, model_bytes: bytes, smoke_tests: Mapping[str, Any]
    ) -> None:
        if self.model_format not in {"onnx", "skops"}:
            raise PackagingError(
                f"Format '{self.model_format}' tidak diizinkan; gunakan 'onnx' atau 'skops'."
            )
        if not model_bytes:
            raise PackagingError("Artefak model kosong.")
        if not self.feature_schema:
            raise PackagingError("Skema fitur tidak boleh kosong.")
        if not smoke_tests.get("cases"):
            raise PackagingError(
                "Paket harus memuat sedikitnya satu kasus uji asap; tanpa itu produksi "
                "tidak dapat memverifikasi model sebelum aktivasi."
            )

        declared = [entry["name"] for entry in self.feature_schema]
        if len(declared) != len(set(declared)):
            raise PackagingError("Nama fitur tidak boleh berulang.")

        # Catching this here rather than letting production reject it saves a
        # round trip the trainer would otherwise have to diagnose remotely.
        for index, case in enumerate(smoke_tests["cases"]):
            missing = set(declared) - set(case.get("features", {}))
            if missing:
                raise PackagingError(
                    f"Kasus uji asap #{index + 1} tidak memuat fitur: "
                    + ", ".join(sorted(missing))
                )


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    """Serialise deterministically so a rebuild produces identical checksums."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
