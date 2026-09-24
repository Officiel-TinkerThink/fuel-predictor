# 03 — Performance per model

**What to build:** `PredictionOutcome` carries its model; `PerformanceMetrics` gains `bias_liters`;
`GetPredictionPerformance` reports `by_model` (every model with matched actuals, plus the active
one); *Kinerja Model* shows the per-model table and relabels the pooled figure; the API returns
`by_model`.

**Blocked by:** 01.

**Status:** in-review

- [x] Two models' predictions matched against actuals give two rows with their own MAE/RMSE/bias.
- [x] A freshly promoted model with no matched actual is listed, saying so.
- [x] Each row shows the MAE the model declared at training next to its field MAE.
