# Model codes, the model on every prediction, and performance per model

Status: in-review

Written 2026-09-24 from the product owner's request.

## Problem

Every prediction already stores which model version made it (`predictions.model_version_id`),
but nobody can see or use that:

- A model's id is `MDL-` plus 32 hex characters when trained in the app, or whatever name the
  package's manifest gives it. Neither is something a person can read out, compare or remember.
- The prediction history and exports don't say which model predicted.
- *Kinerja Model* pools every prediction of every model into one MAE under the heading
  "Seberapa tepat model aktif". After a new model is promoted, its figures are mixed with its
  predecessor's, and there's no telling which model is actually better in the field.
- `model_versions.model_version_id` is `varchar(40)`, but a package's `model_version` may be 64
  characters. A package named longer than 40 is accepted by validation and then fails to register
  on PostgreSQL. SQLite, used by the tests, doesn't enforce the length.

## Decisions

1. **Every model version gets a model code when it is registered**: `M-260924-01`. The date is the
   day training finished (`trained_at`) in site-local time, then the model's sequence number
   among those finished that day. Registration is the moment a model "comes out of training":
   in-app training, or the upload of an externally trained package. A candidate therefore has
   its code before anyone promotes it, and keeps it for good.
2. **The code is stored, unique and never recomputed**, like the operation code (ADR 0016). The
   `M-` prefix keeps it visibly different from an operation code.
3. **Screens and exports name models by code**: the estimate, the prediction history (a new
   *Model* column), bulk-prediction results, model management and comparison, the API
   (`model.model_code`), and the MCP `predict_fuel` result. The long id stays in technical
   details and in the API.
4. **Performance is reported per model.** Each matched actual is attributed to the model that made
   the prediction it's compared with (the operation's latest prediction, as today). The page shows
   one row per model: matched actuals, MAE, RMSE, bias, sMAPE, interval coverage, and the MAE the
   model declared at training for comparison. The active model is always listed, even before any
   actual is matched. The pooled figure stays, but labelled for what it is.
5. **Bias** (mean estimate − actual) joins the metrics. A model can have a fine MAE and still
   under-allocate every day.
6. **Model id columns widen to 64** to match the package contract.

## Out of scope

- Changing which prediction an actual is compared with (the operation's latest).
- Per-model drift. Drift already compares against the active model's reference statistics.

## Issues

- `issues/01-model-code.md`
- `issues/02-model-on-every-prediction.md`
- `issues/03-performance-per-model.md`
