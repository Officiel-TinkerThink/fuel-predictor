# ADR 0009: Accept external models as signed archives with a declared manifest

## Status

Accepted

## Context

ADR 0004 requires manual promotion of candidate models. The production plan moves training off the
production VM entirely: candidates are produced on a developer machine, Colab, or a temporary
runner, then delivered to production as a file. Production must be able to decide whether an
incoming file is safe to load and good enough to serve, without trusting whoever produced it.

Loading a Pickle or Joblib file executes arbitrary code from the file. Accepting such an upload
would make model ingestion equivalent to remote code execution for anyone who reaches the upload
form.

## Decision

Production accepts a ZIP archive containing:

```text
model.onnx | model.skops
manifest.json
input-schema.json
reference-statistics.json
smoke-tests.json
checksum.sha256
```

Trusted serialization formats are ONNX and `skops`, in that order of preference. ONNX is used
whenever the full preprocessing and estimator pipeline can be exported faithfully; `skops` is the
fallback for pipelines ONNX cannot represent. Pickle and Joblib are rejected unconditionally, and
the rejection is not configurable.

`manifest.json` is validated against a published JSON Schema and must declare the model version,
model format and runtime compatibility version, target definition and unit, feature-contract
version with the ordered feature schema, training dataset version, training timestamp and source
revision, global and per-category metrics, labelled test-set size, model size and expected memory
envelope, and a checksum for every archive member.

The server generates every storage path itself from the validated model version. It never uses a
path taken from the archive, and it rejects any member whose name escapes the extraction root or is
absolute. Archive size, extracted size, member count, and compression ratio are all bounded before
extraction so a compression bomb cannot exhaust the disk.

Checksums are verified for every member before the model is loaded. Package signing is supported as
an optional detached signature; when a signing key is configured, an unsigned or badly signed
package is rejected.

## Research and adaptation

- [Python `pickle` documentation](https://docs.python.org/3/library/pickle.html) states plainly that
  unpickling can execute arbitrary code and that it must not be used for untrusted data. That is the
  whole reason for this ADR's format restriction.
- [skops](https://skops.readthedocs.io/en/stable/persistence.html) documents a scikit-learn
  persistence format that does not execute arbitrary code on load and exposes the set of types a
  file will construct before it constructs them. We use its auditable loading path, not a bare load.
- [ONNX Runtime](https://onnxruntime.ai/docs/) provides a graph format with no code execution and a
  small, well-defined runtime. It is preferred because a validated graph is easier to reason about
  than any Python object graph.
- The [PyPI/`zipfile` path traversal class of bugs](https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile.extract)
  — Python's own docs warn that member names may be absolute or contain `..` — motivates generating
  paths server-side rather than sanitising supplied ones.

We deliberately do not accept a bare model file without a manifest. Without a declared feature
contract, production cannot tell whether a candidate is even compatible, and the comparison screen
the plan requires would have nothing to show.

## Consequences

The external training environment must run a packager that produces this archive; that packager
becomes part of this repository so the contract has exactly one implementation. The JSON Schemas are
published artefacts and changing them is a versioned, breaking change.

Because training and serving are now separated by a file format, the production image no longer
needs the training stack once ingestion reaches parity. That reduction is the subject of
[ADR 0011](0011-production-mlflow-topology.md).
