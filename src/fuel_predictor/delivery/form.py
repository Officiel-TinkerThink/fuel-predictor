# ruff: noqa: E501

from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from fuel_predictor.application.actual_fuel import (
    ActualFuelAlreadyRecordedError,
    GetPredictionPerformance,
    RecordActualFuel,
    RecordActualFuelCommand,
)
from fuel_predictor.application.baseline_predictions import (
    BaselineModelNotFoundError,
    BaselineTrainingError,
    GenerateFuelPrediction,
    TrainBaselineCandidate,
)
from fuel_predictor.application.bulk_actual_fuel import BulkActualFuel, BulkActualFuelResult
from fuel_predictor.application.bulk_operation_predictions import (
    BulkOperationPrediction,
    BulkOperationPredictionResult,
)
from fuel_predictor.application.daily_operations import (
    CreateDailyOperation,
    DailyOperationNotFoundError,
)
from fuel_predictor.application.historical_datasets import (
    DatasetVersionNotFoundError,
    HistoricalDatasetImportError,
    HistoricalDatasetImportResult,
    ImportHistoricalDataset,
)
from fuel_predictor.application.model_lifecycle import (
    CandidateModelNotFoundError,
    GetCandidateModelComparison,
    GetModelGovernanceDashboard,
    ModelPromotionNotAllowedError,
    PromoteCandidateModel,
)
from fuel_predictor.application.monitoring import GetMonitoringDashboard
from fuel_predictor.delivery.http import (
    ActualFuelRequest,
    CreateDailyOperationRequest,
    execute_create,
    translate_validation_errors,
)
from fuel_predictor.domain.actual_fuel import ActualFuelRecord
from fuel_predictor.domain.daily_operation import DailyOperation, DailyOperationValidationError
from fuel_predictor.domain.prediction import FuelPrediction, ModelVersion

_UPLOAD_FILE = File(...)
_DEMO_HISTORICAL_DATA = Path(__file__).resolve().parents[3] / "examples" / "riwayat-angber-demo.csv"


def build_form_router(
    create_daily_operation: CreateDailyOperation,
    import_historical_dataset: ImportHistoricalDataset,
    train_baseline_candidate: TrainBaselineCandidate,
    generate_fuel_prediction: GenerateFuelPrediction,
    bulk_operation_prediction: BulkOperationPrediction,
    record_actual_fuel: RecordActualFuel,
    bulk_actual_fuel: BulkActualFuel,
    get_prediction_performance: GetPredictionPerformance,
    promote_candidate_model: PromoteCandidateModel,
    get_candidate_model_comparison: GetCandidateModelComparison,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    get_monitoring_dashboard: GetMonitoringDashboard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/prediksi", response_class=HTMLResponse)
    def show_form() -> HTMLResponse:
        return HTMLResponse(_render_form({}, []))

    @router.get("/impor-data-historis", response_class=HTMLResponse)
    def show_import_form() -> HTMLResponse:
        return HTMLResponse(_render_import_form())

    @router.get("/contoh-data-riwayat.csv")
    def download_demo_historical_data() -> Response:
        return Response(
            content=_DEMO_HISTORICAL_DATA.read_bytes(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="riwayat-angber-demo.csv"'},
        )

    @router.get("/prediksi-operasi-massal", response_class=HTMLResponse)
    def show_bulk_prediction_form() -> HTMLResponse:
        return HTMLResponse(_render_bulk_prediction_form())

    @router.get("/bahan-bakar-aktual", response_class=HTMLResponse)
    def show_actual_fuel_form() -> HTMLResponse:
        return HTMLResponse(_render_actual_fuel_form())

    @router.get("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    def show_bulk_actual_fuel_form() -> HTMLResponse:
        return HTMLResponse(_render_bulk_actual_fuel_form())

    @router.get("/kinerja-prediksi", response_class=HTMLResponse)
    def show_prediction_performance() -> HTMLResponse:
        return HTMLResponse(_render_prediction_performance(get_prediction_performance.execute()))

    @router.get("/pengelolaan-model", response_class=HTMLResponse)
    def show_model_governance() -> HTMLResponse:
        return HTMLResponse(_render_model_governance(get_model_governance_dashboard.execute()))

    @router.get("/pemantauan-operasi", response_class=HTMLResponse)
    def show_monitoring_dashboard() -> HTMLResponse:
        return HTMLResponse(_render_monitoring_dashboard(get_monitoring_dashboard.execute()))

    @router.get("/kandidat-model/{model_version_id}/perbandingan", response_class=HTMLResponse)
    def show_candidate_comparison(model_version_id: str) -> HTMLResponse:
        try:
            comparison = get_candidate_model_comparison.execute(model_version_id)
        except CandidateModelNotFoundError:
            return HTMLResponse(
                _page(
                    "Kandidat model tidak ditemukan",
                    '<main class="shell"><h1>Kandidat model tidak ditemukan</h1><p class="lead">Pilih kandidat yang masih menunggu tinjauan.</p><a class="button-link" href="/pengelolaan-model">Kembali ke pengelolaan model</a></main>',
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(_render_candidate_comparison(comparison))

    @router.post("/operasi-harian", response_class=HTMLResponse)
    async def submit_form(request: Request) -> HTMLResponse:
        form_data = await request.form()
        submitted: dict[str, Any] = {key: str(value) for key, value in form_data.items()}
        submitted_stops = [
            str(value).strip() for value in form_data.getlist("stop_sequence") if str(value).strip()
        ]
        submitted["stop_sequence"] = submitted_stops
        payload: dict[str, Any] = dict(submitted)
        if payload.get("lifting_hours") == "":
            payload["lifting_hours"] = None

        try:
            validated = CreateDailyOperationRequest.model_validate(payload)
            operation = execute_create(validated, create_daily_operation)
        except ValidationError as error:
            errors = translate_validation_errors(error.errors())
            return HTMLResponse(
                _render_form(submitted, errors),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except DailyOperationValidationError as error:
            errors = [{"field": error.field, "message": error.message}]
            return HTMLResponse(
                _render_form(submitted, errors),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        return HTMLResponse(
            _render_success(operation),
            status_code=status.HTTP_201_CREATED,
        )

    @router.post("/impor-data-historis", response_class=HTMLResponse)
    async def submit_import(file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        try:
            result = import_historical_dataset.execute(
                file.filename or "berkas-impor", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_import_form(error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return HTMLResponse(_render_import_success(result), status_code=status.HTTP_201_CREATED)

    @router.post(
        "/dataset-versions/{dataset_version_id}/latih-kandidat-baseline",
        response_class=HTMLResponse,
    )
    def train_baseline(dataset_version_id: str) -> HTMLResponse:
        try:
            model = train_baseline_candidate.execute(dataset_version_id)
        except (BaselineTrainingError, DatasetVersionNotFoundError) as error:
            return HTMLResponse(
                _render_training_error(dataset_version_id, str(error)),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return HTMLResponse(_render_training_success(model), status_code=status.HTTP_201_CREATED)

    @router.post("/kandidat-model/{model_version_id}/promosikan", response_class=HTMLResponse)
    def promote_candidate(model_version_id: str) -> HTMLResponse:
        try:
            model = promote_candidate_model.execute(model_version_id)
        except CandidateModelNotFoundError:
            return HTMLResponse(
                _page(
                    "Kandidat model tidak ditemukan",
                    '<main class="shell"><h1>Kandidat model tidak ditemukan</h1><a class="button-link" href="/pengelolaan-model">Kembali</a></main>',
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except ModelPromotionNotAllowedError as error:
            return HTMLResponse(
                _page(
                    "Promosi model tidak dapat dilakukan",
                    f'<main class="shell"><h1>Promosi model tidak dapat dilakukan</h1><p class="lead">{escape(str(error))}</p><a class="button-link" href="/pengelolaan-model">Kembali</a></main>',
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        return HTMLResponse(_render_promotion_success(model), status_code=status.HTTP_200_OK)

    @router.post("/prediksi-operasi-massal", response_class=HTMLResponse)
    async def submit_bulk_prediction(file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        try:
            result = bulk_operation_prediction.execute(
                file.filename or "berkas-prediksi-operasi", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_bulk_prediction_form(error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except BaselineModelNotFoundError:
            return HTMLResponse(
                _render_bulk_prediction_form(
                    "Latih kandidat baseline dari dataset tervalidasi sebelum membuat prediksi massal."
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        return HTMLResponse(
            _render_bulk_prediction_success(result), status_code=status.HTTP_201_CREATED
        )

    @router.post("/bahan-bakar-aktual", response_class=HTMLResponse)
    async def submit_actual_fuel(request: Request) -> HTMLResponse:
        form_data = await request.form()
        submitted = {key: str(value) for key, value in form_data.items()}
        try:
            payload = {key: value for key, value in submitted.items() if key != "operation_id"}
            validated = ActualFuelRequest.model_validate(payload)
            record = record_actual_fuel.execute(
                RecordActualFuelCommand(
                    operation_id=submitted.get("operation_id", "").strip(),
                    actual_fuel_liters=validated.actual_fuel_liters,
                    measurement_source=validated.measurement_source,
                )
            )
        except ValidationError as error:
            return HTMLResponse(
                _render_actual_fuel_form(submitted, translate_validation_errors(error.errors())),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except DailyOperationValidationError as error:
            return HTMLResponse(
                _render_actual_fuel_form(
                    submitted, [{"field": error.field, "message": error.message}]
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        except ActualFuelAlreadyRecordedError:
            return HTMLResponse(
                _render_actual_fuel_form(
                    submitted,
                    [
                        {
                            "field": "operation_id",
                            "message": "Bahan bakar aktual untuk operasi ini sudah tercatat.",
                        }
                    ],
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        except DailyOperationNotFoundError:
            return HTMLResponse(
                _render_actual_fuel_form(
                    submitted, [{"field": "operation_id", "message": "ID operasi tidak ditemukan."}]
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return HTMLResponse(
            _render_actual_fuel_success(record), status_code=status.HTTP_201_CREATED
        )

    @router.post("/bahan-bakar-aktual-massal", response_class=HTMLResponse)
    async def submit_bulk_actual_fuel(file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        try:
            result = bulk_actual_fuel.execute(
                file.filename or "berkas-bbm-aktual", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_bulk_actual_fuel_form(error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return HTMLResponse(
            _render_bulk_actual_fuel_success(result), status_code=status.HTTP_201_CREATED
        )

    @router.post("/operasi-harian/{operation_id}/prediksi", response_class=HTMLResponse)
    def submit_prediction(operation_id: str) -> HTMLResponse:
        try:
            prediction = generate_fuel_prediction.execute(operation_id)
        except BaselineModelNotFoundError:
            return HTMLResponse(
                _page(
                    "Prediksi belum tersedia",
                    """
                    <main class="shell"><h1>Prediksi belum tersedia</h1>
                    <p class="lead">Latih kandidat baseline dari dataset tervalidasi sebelum membuat
                    estimasi untuk operasi ini.</p><a class="button-link" href="/">Kembali</a></main>
                    """,
                ),
                status_code=status.HTTP_409_CONFLICT,
            )
        return HTMLResponse(
            _render_prediction_success(prediction), status_code=status.HTTP_201_CREATED
        )

    return router


def _render_actual_fuel_form(
    values: dict[str, Any] | None = None, errors: list[dict[str, str]] | None = None
) -> str:
    values = values or {}
    errors = errors or []
    error_summary = ""
    if errors:
        error_summary = (
            '<section class="errors" role="alert" aria-labelledby="error-title" tabindex="-1">'
            '<h2 id="error-title">Bahan bakar aktual belum dapat disimpan</h2><ul>'
            + "".join(f"<li>{escape(error['message'])}</li>" for error in errors)
            + "</ul></section>"
        )
    return _page(
        "Catat Bahan Bakar Aktual",
        f"""
        <main class="shell">
          <header><p class="eyebrow">UMPAN BALIK OPERASI</p><h1>Catat Bahan Bakar Aktual</h1>
          <p class="lead">Masukkan konsumsi BBM setelah operasi selesai. Nilai ini disimpan
          terpisah dari bahan bakar disiapkan.</p></header>
          {error_summary}
          <form method="post" action="/bahan-bakar-aktual" novalidate>
            <fieldset><legend>Hasil operasi</legend>
              <div class="field"><label for="operation_id">ID operasi</label>
                <input id="operation_id" name="operation_id" required value="{escape(str(values.get("operation_id", "")))}">
                <small>Gunakan ID OPR-... dari operasi yang sudah disimpan.</small></div>
              <div class="field"><label for="actual_fuel_liters">Bahan bakar aktual</label>
                <div class="unit-input"><input id="actual_fuel_liters" name="actual_fuel_liters" type="number" min="0.01" step="0.01" required value="{escape(str(values.get("actual_fuel_liters", "")))}"><span>L</span></div></div>
              <div class="field"><label for="measurement_source">Sumber pengukuran</label>
                <select id="measurement_source" name="measurement_source">
                  {_option("manual_entry", "Catatan manual", values.get("measurement_source", "manual_entry"))}
                  {_option("fuel_meter", "Meter BBM", values.get("measurement_source", "manual_entry"))}
                  {_option("receipt", "Bukti/nota", values.get("measurement_source", "manual_entry"))}
                </select></div>
            </fieldset><button type="submit">Simpan bahan bakar aktual</button></form>
          <p><a href="/bahan-bakar-aktual-massal">Impor aktual massal</a> · <a href="/kinerja-prediksi">Lihat kinerja prediksi</a> · <a href="/">Kembali</a></p>
        </main><script>document.querySelector('.errors')?.focus();</script>
        """,
    )


def _render_actual_fuel_success(record: ActualFuelRecord) -> str:
    return _page(
        "Bahan Bakar Aktual Tersimpan",
        f"""
        <main class="shell success"><p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">UMPAN BALIK TERSIMPAN</p><h1>Bahan bakar aktual tersimpan</h1>
          <p class="lead">{_format_decimal(record.actual_fuel_liters)} L tercatat untuk <strong>{escape(record.operation_id)}</strong>.</p>
          <p>Nilai prepared fuel dan prediksi tidak diubah. Status: {escape(record.status.value)}.</p>
          <p><a class="button-link" href="/bahan-bakar-aktual">Catat operasi lain</a> <a href="/kinerja-prediksi">Lihat kinerja prediksi</a></p>
        </main>
        """,
    )


def _render_bulk_actual_fuel_form(error: str | None = None) -> str:
    error_summary = (
        '<section class="errors" role="alert"><h2>Berkas belum dapat diproses</h2>'
        f"<p>{escape(error)}</p></section>"
        if error is not None
        else ""
    )
    return _page(
        "Impor Bahan Bakar Aktual",
        f"""
        <main class="shell"><header><p class="eyebrow">UMPAN BALIK OPERASI</p>
          <h1>Impor Bahan Bakar Aktual</h1><p class="lead">Unggah CSV atau Excel .xlsx.
          Baris valid tetap disimpan; ID tidak cocok dan nilai tidak valid dikarantina.</p></header>
          {error_summary}
          <p><a href="/api/v1/bulk-actual-fuel/template?format=xlsx">Unduh template Excel</a> · <a href="/api/v1/bulk-actual-fuel/template?format=csv">Unduh template CSV</a></p>
          <form method="post" action="/bahan-bakar-aktual-massal" enctype="multipart/form-data">
            <div class="field"><label for="file">Berkas bahan bakar aktual</label>
            <input id="file" name="file" type="file" accept=".csv,.xlsx" required>
            <small>Kolom wajib: ID operasi dan bahan bakar aktual (L). Sumber pengukuran opsional.</small></div>
            <button type="submit">Validasi dan simpan aktual</button></form>
          <p><a href="/bahan-bakar-aktual">Catat satu operasi</a> · <a href="/">Kembali</a></p>
        </main>
        """,
    )


def _render_bulk_actual_fuel_success(result: BulkActualFuelResult) -> str:
    accepted_rows = "".join(
        "<tr>"
        f"<td>{escape(row.source.sheet_name)} {row.source.row_number}</td>"
        f"<td>{escape(row.actual_fuel.operation_id)}</td>"
        f"<td>{_format_decimal(row.actual_fuel.actual_fuel_liters)} L</td>"
        f"<td>{escape(row.actual_fuel.measurement_source.value)}</td></tr>"
        for row in result.accepted_rows
    )
    corrections = "".join(
        f"<li><strong>{escape(issue.source.sheet_name)} baris {issue.source.row_number}:</strong> "
        f"{escape('; '.join(reason.message for reason in issue.reasons))}</li>"
        for issue in result.correction_report
    )
    correction_section = (
        f'<section class="corrections"><h2>Laporan koreksi</h2><ul>{corrections}</ul></section>'
        if corrections
        else ""
    )
    return _page(
        "Impor Bahan Bakar Aktual Selesai",
        f"""
        <main class="shell success"><p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">IMPOR AKTUAL SELESAI</p><h1>Bahan bakar aktual sudah diproses</h1>
          <p class="lead">{len(result.accepted_rows)} baris valid disimpan. {len(result.correction_report)} baris dikarantina. {result.ignored_blank_row_count} baris kosong diabaikan.</p>
          <table><thead><tr><th>Baris sumber</th><th>ID operasi</th><th>Aktual</th><th>Sumber</th></tr></thead><tbody>{accepted_rows}</tbody></table>
          {correction_section}<p><a href="/kinerja-prediksi">Lihat kinerja prediksi</a></p>
        </main>
        """,
    )


def _render_prediction_performance(report: Any) -> str:
    overall = report.overall
    if overall.matched_record_count == 0:
        summary = "Belum ada bahan bakar aktual yang dapat dicocokkan dengan prediksi."
    else:
        summary = (
            f"{overall.matched_record_count} catatan aktual sudah cocok dengan prediksi terakhir."
        )
    rows = (
        "".join(
            "<tr>"
            f"<td>{escape(category.value)}</td><td>{metrics.matched_record_count}</td>"
            f"<td>{_metric(metrics.mae_liters, 'L')}</td><td>{_metric(metrics.rmse_liters, 'L')}</td>"
            f"<td>{_metric(metrics.smape_percent, '%')}</td><td>{_metric(metrics.interval_coverage_percent, '%')}</td></tr>"
            for category, metrics in report.by_vehicle_category
        )
        or '<tr><td colspan="6">Belum cukup data yang cocok.</td></tr>'
    )
    return _page(
        "Kinerja Prediksi",
        f"""
        <main class="shell"><header><p class="eyebrow">EVALUASI MODEL</p><h1>Kinerja Prediksi</h1>
          <p class="lead">{summary} Metrik memakai estimasi kebutuhan BBM, bukan alokasi rekomendasi.</p></header>
          <section class="summary-card"><h2>Keseluruhan</h2><dl><dt>MAE</dt><dd>{_metric(overall.mae_liters, "L")}</dd><dt>RMSE</dt><dd>{_metric(overall.rmse_liters, "L")}</dd><dt>sMAPE</dt><dd>{_metric(overall.smape_percent, "%")}</dd><dt>Cakupan interval</dt><dd>{_metric(overall.interval_coverage_percent, "%")}</dd></dl></section>
          <h2>Per kategori ANGBER</h2><table><thead><tr><th>Kategori</th><th>Cocok</th><th>MAE</th><th>RMSE</th><th>sMAPE</th><th>Cakupan interval</th></tr></thead><tbody>{rows}</tbody></table>
          <p><a class="button-link" href="/bahan-bakar-aktual">Catat bahan bakar aktual</a></p>
        </main>
        """,
    )


def _metric(value: float | None, unit: str) -> str:
    return "Belum cukup data" if value is None else f"{_format_decimal(value)} {unit}"


def _render_model_governance(dashboard: Any) -> str:
    active = (
        f"<strong>{escape(dashboard.active_model.model_version_id)}</strong>"
        if dashboard.active_model
        else "Belum ada model aktif"
    )
    candidates = (
        "".join(
            "<tr>"
            f"<td>{escape(candidate.model_version_id)}</td><td>{escape(candidate.dataset_version_id)}</td>"
            f'<td><a href="/kandidat-model/{escape(candidate.model_version_id)}/perbandingan">Bandingkan</a></td>'
            f'<td><form method="post" action="/kandidat-model/{escape(candidate.model_version_id)}/promosikan"><button>Promosikan manual</button></form></td>'
            "</tr>"
            for candidate in dashboard.candidate_models
        )
        or '<tr><td colspan="4">Belum ada kandidat yang menunggu tinjauan.</td></tr>'
    )
    return _page(
        "Pengelolaan Model",
        f"""
        <main class="shell"><header><p class="eyebrow">TATA KELOLA MODEL</p><h1>Pengelolaan Model</h1>
          <p class="lead">{escape(dashboard.recommendation)}</p></header>
          <section class="summary-card"><h2>Model aktif</h2><p>{active}</p>
          <p>MAE aktif: {_metric(dashboard.active_performance.mae_liters, "L") if dashboard.active_performance else "Belum cukup data"}</p></section>
          <h2>Kandidat menunggu keputusan</h2><table><thead><tr><th>Model</th><th>Dataset</th><th>Evaluasi</th><th>Keputusan</th></tr></thead><tbody>{candidates}</tbody></table>
          <p class="lead">Promosi tidak pernah dilakukan otomatis. Promosi baru berlaku setelah tombol tindakan manual dipilih.</p>
        </main>
        """,
    )


def _render_monitoring_dashboard(dashboard: Any) -> str:
    alerts = (
        "".join(
            "<li><strong>"
            f"{escape(alert.severity.value.upper())}</strong> — {escape(alert.message)}"
            f" <small>({escape(alert.alert_key)})</small></li>"
            for alert in dashboard.active_alerts
        )
        or "<li>Tidak ada alert aktif.</li>"
    )
    issues = (
        "".join(
            f"<li>{escape(issue.dataset_version_id)} · {escape(issue.sheet_name)} baris "
            f"{issue.row_number}: {escape('; '.join(issue.messages))}</li>"
            for issue in dashboard.unresolved_data_quality_issues
        )
        or "<li>Tidak ada baris yang perlu diperbaiki.</li>"
    )
    datasets = (
        "".join(
            "<tr>"
            f"<td>{escape(item.dataset_version_id)}</td><td>{escape(item.source_filename)}</td>"
            f"<td>{item.valid_operation_count}</td><td>{item.quarantined_row_count}</td>"
            "</tr>"
            for item in dashboard.dataset_validation_summaries
        )
        or '<tr><td colspan="4">Belum ada dataset.</td></tr>'
    )
    missing = (
        "".join(
            f"<li>{escape(item.operation_id)} · prediksi {escape(item.prediction_id)}</li>"
            for item in dashboard.missing_actual_predictions
        )
        or "<li>Tidak ada prediksi yang lewat batas waktu.</li>"
    )
    trend = (
        "".join(
            f"<tr><td>{escape(point.observed_at.date().isoformat())}</td>"
            f"<td>{point.matched_record_count}</td><td>{_metric(point.mae_liters, 'L')}</td></tr>"
            for point in dashboard.rolling_error_trend
        )
        or '<tr><td colspan="3">Belum ada aktual yang cocok.</td></tr>'
    )
    categories = (
        "".join(
            f"<tr><td>{escape(item.vehicle_category.value)}</td><td>{item.matched_record_count}</td>"
            f"<td>{_metric(item.rolling_mae_liters, 'L')}</td>"
            f"<td>{'Perlu ditinjau' if item.degraded else 'Dalam ambang'}</td></tr>"
            for item in dashboard.category_degradation
        )
        or '<tr><td colspan="4">Belum ada aktual yang cocok.</td></tr>'
    )
    drift = dashboard.feature_drift
    drift_status = {
        "ready": "tersedia",
        "insufficient_data": "belum cukup data",
        "no_active_model": "belum ada model aktif",
    }.get(drift.status, drift.status)
    return _page(
        "Pemantauan Operasi dan Alert",
        f"""
        <main class="shell"><header><p class="eyebrow">PEMANTAUAN LOKAL</p>
          <h1>Pemantauan Operasi dan Alert</h1><p class="lead">Alert ini hanya tersimpan di aplikasi lokal.
          Tidak ada email/pesan keluar. Tidak ada promosi model otomatis.</p></header>
          <section class="errors"><h2>Alert aktif ({len(dashboard.active_alerts)})</h2><ul>{alerts}</ul></section>
          <h2>Kualitas data</h2><p>{dashboard.unresolved_data_quality_issue_count} isu belum selesai.</p><ul>{issues}</ul>
          <table><thead><tr><th>Dataset</th><th>Berkas</th><th>Valid</th><th>Dikarantina</th></tr></thead><tbody>{datasets}</tbody></table>
          <h2>Actual Fuel tertunda</h2><p>Prediksi tanpa aktual setelah {dashboard.missing_actual_after_days} hari: {dashboard.missing_actual_prediction_count}.</p><ul>{missing}</ul>
          <h2>Drift fitur</h2><p>Status: {escape(drift_status)}. Ambang share drift: {_format_decimal(drift.threshold)}.
          Share saat ini: {_metric(drift.drift_share, "")}. Fitur bergeser: {escape(", ".join(drift.drifting_features) or "tidak ada")}.</p>
          <h2>Tren kesalahan bergulir</h2><table><thead><tr><th>Tanggal aktual</th><th>Data cocok</th><th>MAE</th></tr></thead><tbody>{trend}</tbody></table>
          <h2>Degradasi per kategori</h2><p>Ambang MAE: {_format_decimal(dashboard.degradation_mae_threshold_liters)} L.</p><table><thead><tr><th>Kategori</th><th>Data cocok</th><th>MAE bergulir</th><th>Status</th></tr></thead><tbody>{categories}</tbody></table>
          <p><a href="/bahan-bakar-aktual">Catat bahan bakar aktual</a> · <a href="/pengelolaan-model">Kelola model</a></p>
        </main>
        """,
    )


def _render_candidate_comparison(comparison: Any) -> str:
    overall_active = (
        _metric(comparison.active_overall.mae_liters, "L")
        if comparison.active_overall is not None
        else "Belum ada model aktif"
    )
    rows = (
        "".join(
            "<tr>"
            f"<td>{escape(item.vehicle_category.value)}</td><td>{_metric(item.candidate.mae_liters, 'L')}</td>"
            f"<td>{_metric(item.active.mae_liters, 'L') if item.active else '—'}</td></tr>"
            for item in comparison.by_vehicle_category
        )
        or '<tr><td colspan="3">Belum ada bahan bakar aktual untuk evaluasi.</td></tr>'
    )
    return _page(
        "Perbandingan Kandidat Model",
        f"""
        <main class="shell"><header><p class="eyebrow">PERBANDINGAN MANUAL</p><h1>Perbandingan Kandidat Model</h1>
          <p class="lead">Metrik dihitung ulang pada operasi yang memiliki bahan bakar aktual. Tindakan ini tidak mengubah model aktif.</p></header>
          <dl><dt>Kandidat</dt><dd>{escape(comparison.candidate.model_version_id)}</dd><dt>MAE kandidat</dt><dd>{_metric(comparison.candidate_overall.mae_liters, "L")}</dd><dt>MAE model aktif</dt><dd>{overall_active}</dd></dl>
          <h2>MAE per kategori ANGBER</h2><table><thead><tr><th>Kategori</th><th>Kandidat</th><th>Aktif</th></tr></thead><tbody>{rows}</tbody></table>
          <form method="post" action="/kandidat-model/{escape(comparison.candidate.model_version_id)}/promosikan"><button>Promosikan kandidat secara manual</button></form>
          <p><a href="/pengelolaan-model">Kembali ke pengelolaan model</a></p></main>
        """,
    )


def _render_promotion_success(model: ModelVersion) -> str:
    return _page(
        "Model dipromosikan",
        f"""
        <main class="shell success"><p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">PROMOSI MANUAL SELESAI</p><h1>Model aktif diperbarui</h1>
          <p class="lead">{escape(model.model_version_id)} kini menjadi model aktif. Riwayat model aktif sebelumnya tetap tersimpan.</p>
          <p><a class="button-link" href="/">Kembali ke perencanaan operasi</a></p></main>
        """,
    )


def _render_form(values: dict[str, Any], errors: list[dict[str, str]]) -> str:
    activity_mode = values.get("activity_mode", "transport")
    error_summary = ""
    if errors:
        items = "".join(f"<li>{escape(item['message'])}</li>" for item in errors)
        error_summary = (
            '<section class="errors" role="alert" aria-labelledby="error-title" tabindex="-1">'
            '<h2 id="error-title">Periksa kembali data operasi</h2>'
            f"<ul>{items}</ul></section>"
        )
    stop_sequence = values.get("stop_sequence", ["", ""])
    if not isinstance(stop_sequence, list):
        stop_sequence = ["", ""]
    if not stop_sequence:
        stop_sequence = ["", ""]
    stop_inputs = "".join(
        _render_stop_input(str(value), index) for index, value in enumerate(stop_sequence)
    )

    return _page(
        "Buat Operasi Harian",
        f"""
        <main class="shell">
          <header>
            <p class="eyebrow">PERENCANAAN BAHAN BAKAR</p>
            <h1>Buat Operasi Harian</h1>
            <p class="lead">Catat satu rencana operasi ANGBER secara lengkap dan konsisten.</p>
            <p><a href="/impor-data-historis">Impor data historis ANGBER</a> · <a href="/prediksi-operasi-massal">Prediksi operasi massal</a> · <a href="/bahan-bakar-aktual">Catat BBM aktual</a> · <a href="/kinerja-prediksi">Kinerja prediksi</a> · <a href="/pemantauan-operasi">Pemantauan operasi dan alert</a></p>
          </header>
          {error_summary}
          <form method="post" action="/operasi-harian" novalidate>
            <fieldset>
              <legend>Detail operasi</legend>
              <div class="field">
                <label for="vehicle_category">Kategori kendaraan</label>
                <select id="vehicle_category" name="vehicle_category" required>
                  {_option("ANGBER", "ANGBER — Angkutan Berat", values.get("vehicle_category", "ANGBER"))}
                </select>
              </div>
              <div class="field">
                <label for="activity_mode">Mode aktivitas</label>
                <select id="activity_mode" name="activity_mode" required>
                  {_option("transport", "Angkut", activity_mode)}
                  {_option("lifting", "Lifting", activity_mode)}
                  {_option("transport_and_lifting", "Angkut dan lifting", activity_mode)}
                </select>
                <small>Pilih aktivitas yang mencakup seluruh operasi hari ini.</small>
              </div>
              <div class="field" id="lifting-field">
                <label for="lifting_hours">Jam lifting</label>
                <div class="unit-input">
                  <input id="lifting_hours" name="lifting_hours" type="number" min="0.01"
                    step="0.01" inputmode="decimal"
                    value="{escape(values.get("lifting_hours", ""))}">
                  <span>jam</span>
                </div>
                <small>Wajib untuk mode yang mencakup lifting.</small>
              </div>
              <div class="field">
                <label for="total_distance_km">Jarak total cadangan</label>
                <div class="unit-input">
                  <input id="total_distance_km" name="total_distance_km" type="number"
                    min="0.01" step="0.01" inputmode="decimal" required
                    value="{escape(values.get("total_distance_km", ""))}">
                  <span>km</span>
                </div>
                <small>Dipakai bila penyedia rute tidak tersedia; jika rute berhasil dihitung,
                  sistem memakai hasil hitung rute.</small>
              </div>
              <fieldset class="stops-field" aria-describedby="stops-help">
                <legend>Urutan pemberhentian</legend>
                <p id="stops-help" class="hint">Masukkan lokasi sesuai urutan pelaksanaan.
                  Sistem tidak akan mengoptimalkan atau mengubah urutannya.</p>
                <div id="stop-sequence">{stop_inputs}</div>
                <button class="secondary-button" id="add-stop" type="button">Tambah pemberhentian</button>
              </fieldset>
              <div class="field">
                <label for="distance_source">Sumber jarak</label>
                <select id="distance_source" name="distance_source" required>
                  {_option("manual", "Input manual", values.get("distance_source", "manual"))}
                  {_option("routing_provider", "Penyedia rute", values.get("distance_source", "manual"))}
                </select>
              </div>
            </fieldset>
            <button type="submit">Simpan operasi harian</button>
          </form>
        </main>
        <script>
          const mode = document.querySelector('#activity_mode');
          const lifting = document.querySelector('#lifting_hours');
          const liftingField = document.querySelector('#lifting-field');
          function syncLifting() {{
            const applies = mode.value === 'lifting' || mode.value === 'transport_and_lifting';
            lifting.required = applies;
            lifting.disabled = !applies;
            liftingField.hidden = !applies;
            if (!applies) lifting.value = '';
          }}
          mode.addEventListener('change', syncLifting);
          syncLifting();
          const sequence = document.querySelector('#stop-sequence');
          function controls(index) {{
            return `<div class="stop-controls"><button type="button" data-action="up" aria-label="Naikkan urutan pemberhentian ${"{"}index + 1{"}"}">↑</button><button type="button" data-action="down" aria-label="Turunkan urutan pemberhentian ${"{"}index + 1{"}"}">↓</button><button type="button" data-action="remove" aria-label="Hapus pemberhentian ${"{"}index + 1{"}"}">Hapus pemberhentian</button></div>`;
          }}
          function stopRow(value = '') {{
            const row = document.createElement('div');
            row.className = 'stop-row';
            row.innerHTML = `<label>Pemberhentian <input name="stop_sequence" type="text" value="${"{"}value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'){"}"}" autocomplete="off"></label>${"{"}controls(sequence.children.length){"}"}`;
            return row;
          }}
          function refreshStopControls() {{
            [...sequence.children].forEach((row, index) => {{
              row.querySelector('.stop-controls').innerHTML = controls(index);
            }});
          }}
          document.querySelector('#add-stop').addEventListener('click', () => {{
            sequence.append(stopRow());
            refreshStopControls();
            sequence.lastElementChild.querySelector('input').focus();
          }});
          sequence.addEventListener('click', (event) => {{
            const button = event.target.closest('button[data-action]');
            if (!button) return;
            const row = button.closest('.stop-row');
            if (button.dataset.action === 'remove') row.remove();
            if (button.dataset.action === 'up' && row.previousElementSibling) {{
              sequence.insertBefore(row, row.previousElementSibling);
            }}
            if (button.dataset.action === 'down' && row.nextElementSibling) {{
              sequence.insertBefore(row.nextElementSibling, row);
            }}
            refreshStopControls();
          }});
          refreshStopControls();
          document.querySelector('.errors')?.focus();
        </script>
        """,
    )


def _render_import_form(error: str | None = None) -> str:
    error_summary = ""
    if error is not None:
        error_summary = (
            '<section class="errors" role="alert" aria-labelledby="error-title" tabindex="-1">'
            '<h2 id="error-title">Berkas belum dapat diimpor</h2>'
            f"<p>{escape(error)}</p></section>"
        )
    return _page(
        "Impor Data Historis ANGBER",
        f"""
        <main class="shell">
          <header>
            <p class="eyebrow">DATA PELATIHAN</p>
            <h1>Impor Data Historis ANGBER</h1>
            <p class="lead">Unggah CSV atau Excel .xlsx. Baris kosong kalender diabaikan;
              baris yang perlu diperbaiki akan dikarantina dalam laporan koreksi.</p>
          </header>
          {error_summary}
          <p class="demo-note"><strong>Untuk demo:</strong> <a href="/contoh-data-riwayat.csv" download>unduh data contoh yang siap diimpor</a>.</p>
          <form method="post" action="/impor-data-historis" enctype="multipart/form-data">
            <div class="field">
              <label for="file">Berkas historis</label>
              <input id="file" name="file" type="file" accept=".csv,.xlsx" required>
              <small>Kolom wajib: kategori ANGBER, mode aktivitas, jarak total, bahan bakar
                disiapkan, dan sumber jarak. Kolom jam lifting diterima dengan variasi header.</small>
            </div>
            <button type="submit">Validasi dan buat versi dataset</button>
          </form>
          <p><a href="/prediksi-operasi-massal">Prediksi operasi massal</a> · <a href="/">Kembali ke operasi harian</a></p>
        </main>
        <script>document.querySelector('.errors')?.focus();</script>
        """,
    )


def _render_bulk_prediction_form(error: str | None = None) -> str:
    error_summary = ""
    if error is not None:
        error_summary = (
            '<section class="errors" role="alert" aria-labelledby="error-title">'
            '<h2 id="error-title">Prediksi massal belum dapat diproses</h2>'
            f"<p>{escape(error)}</p></section>"
        )
    return _page(
        "Prediksi Operasi Massal",
        f"""
        <main class="shell">
          <header>
            <p class="eyebrow">PERENCANAAN BAHAN BAKAR</p>
            <h1>Prediksi Operasi Massal</h1>
            <p class="lead">Unggah rencana operasi CSV atau Excel .xlsx. Baris yang valid tetap
              diprediksi, sementara baris lain dikarantina bersama alasan koreksinya.</p>
          </header>
          {error_summary}
          <p><a href="/api/v1/bulk-operation-predictions/template?format=xlsx">Unduh template Excel</a> ·
            <a href="/api/v1/bulk-operation-predictions/template?format=csv">Unduh template CSV</a></p>
          <form method="post" action="/prediksi-operasi-massal" enctype="multipart/form-data">
            <div class="field">
              <label for="file">Berkas rencana operasi</label>
              <input id="file" name="file" type="file" accept=".csv,.xlsx" required>
              <small>Kolom wajib: kategori ANGBER, mode aktivitas, jarak total, dan sumber jarak.
                Jam lifting serta urutan pemberhentian bersifat opsional.</small>
            </div>
            <button type="submit">Buat prediksi massal</button>
          </form>
          <p><a href="/">Kembali ke operasi harian</a></p>
        </main>
        """,
    )


def _render_bulk_prediction_success(result: BulkOperationPredictionResult) -> str:
    accepted_rows = "".join(
        "<tr>"
        f"<td>{escape(row.source.sheet_name)} {row.source.row_number}</td>"
        f"<td>{escape(row.operation.operation_id)}</td>"
        f"<td>{_format_decimal(row.prediction.estimated_fuel_requirement_liters)} L</td>"
        f"<td>{_format_decimal(row.prediction.recommended_allocation_liters)} L</td>"
        f"<td>{escape(row.prediction.model.model_version_id)}</td>"
        "</tr>"
        for row in result.accepted_rows
    )
    corrections = "".join(
        "<li><strong>"
        f"{escape(issue.source.sheet_name)} baris {issue.source.row_number}:</strong> "
        f"{escape('; '.join(reason.message for reason in issue.reasons))}</li>"
        for issue in result.correction_report
    )
    correction_section = (
        f'<section class="corrections"><h2>Laporan koreksi</h2><ul>{corrections}</ul></section>'
        if corrections
        else ""
    )
    return _page(
        "Prediksi Operasi Massal Selesai",
        f"""
        <main class="shell success">
          <p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">PREDIKSI MASSAL SELESAI</p>
          <h1>Rencana operasi sudah diproses</h1>
          <p class="lead">{len(result.accepted_rows)} baris valid memperoleh ID operasi dan prediksi.
            {len(result.correction_report)} baris dikarantina. {result.ignored_blank_row_count} baris kosong diabaikan.</p>
          <table><thead><tr><th>Baris sumber</th><th>ID operasi</th><th>Estimasi kebutuhan BBM</th><th>Alokasi rekomendasi</th><th>Model</th></tr></thead><tbody>{accepted_rows}</tbody></table>
          {correction_section}
          <p><a class="button-link" href="/prediksi-operasi-massal">Prediksi berkas lain</a></p>
        </main>
        """,
    )


def _render_import_success(result: HistoricalDatasetImportResult) -> str:
    dataset = result.dataset_version
    correction_summary = (
        f"{dataset.quarantined_row_count} baris dikarantina"
        if dataset.quarantined_row_count == 1
        else f"{dataset.quarantined_row_count} baris dikarantina"
    )
    corrections = ""
    if result.correction_report:
        rows = "".join(
            "<li><strong>"
            f"{escape(issue.source.sheet_name)} baris {issue.source.row_number}:</strong> "
            f"{escape('; '.join(reason.message for reason in issue.reasons))}</li>"
            for issue in result.correction_report
        )
        corrections = f"""
          <section class="corrections" aria-labelledby="corrections-title">
            <h2 id="corrections-title">Laporan koreksi</h2>
            <p>Perbaiki baris berikut lalu unggah kembali berkasnya. Data valid tetap tersimpan
              dalam versi ini.</p>
            <ul>{rows}</ul>
          </section>
        """
    training_step = (
        f"""
          <section class="next-step" aria-labelledby="training-title">
            <h2 id="training-title">Langkah berikutnya: latih kandidat baseline</h2>
            <p>Latih secara manual memakai {dataset.valid_operation_count} operasi valid pada dataset ini.</p>
            <form method="post" action="/dataset-versions/{escape(dataset.dataset_version_id)}/latih-kandidat-baseline">
              <button type="submit">Latih kandidat baseline secara manual</button>
            </form>
          </section>
        """
        if dataset.valid_operation_count >= 2
        else """
          <section class="next-step">
            <h2>Belum dapat melatih kandidat baseline</h2>
            <p>Tambahkan sedikitnya dua operasi valid, lalu impor kembali sebagai versi dataset baru.</p>
          </section>
        """
    )
    return _page(
        "Dataset historis berhasil diimpor",
        f"""
        <main class="shell success">
          <p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">DATASET TERVERIFIKASI</p>
          <h1>Dataset versi {dataset.version} berhasil dibuat</h1>
          <p class="lead">{dataset.valid_operation_count} operasi valid siap digunakan untuk pelatihan. {correction_summary}. {dataset.ignored_blank_row_count} baris kalender kosong diabaikan.</p>
          <dl>
            <dt>ID versi dataset</dt><dd>{escape(dataset.dataset_version_id)}</dd>
            <dt>Berkas sumber</dt><dd>{escape(dataset.source_filename)}</dd>
            <dt>Operasi valid</dt><dd>{dataset.valid_operation_count}</dd>
            <dt>Baris dikarantina</dt><dd>{dataset.quarantined_row_count}</dd>
          </dl>
          {corrections}
          {training_step}
          <a class="button-link" href="/impor-data-historis">Impor data lain</a>
        </main>
        """,
    )


def _render_training_success(model: ModelVersion) -> str:
    return _page(
        "Kandidat baseline siap digunakan",
        f"""
        <main class="shell success">
          <p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">KANDIDAT DILATIH MANUAL</p>
          <h1>Kandidat baseline siap digunakan</h1>
          <p class="lead">Kandidat regresi linear ini dilatih dari riwayat bahan bakar disiapkan.
            Ia belum menyatakan konsumsi aktual dan tidak dipromosikan secara otomatis.</p>
          <dl>
            <dt>ID model</dt><dd>{escape(model.model_version_id)}</dd>
            <dt>Versi dataset</dt><dd>{escape(model.dataset_version_id)}</dd>
            <dt>Data pelatihan</dt><dd>{model.training_row_count} operasi valid</dd>
            <dt>Versi fitur</dt><dd>{escape(model.feature_version)}</dd>
          </dl>
          <p class="lead">Kandidat belum dipakai untuk prediksi. Bandingkan dan promosikan secara manual bila disetujui.</p>
          <a class="button-link" href="/pengelolaan-model">Tinjau kandidat model</a>
        </main>
        """,
    )


def _render_training_error(dataset_version_id: str, error: str) -> str:
    return _page(
        "Kandidat baseline belum dapat dilatih",
        f"""
        <main class="shell">
          <h1>Kandidat baseline belum dapat dilatih</h1>
          <p class="lead">{escape(error)}</p>
          <p>ID versi dataset: <strong>{escape(dataset_version_id)}</strong></p>
          <a class="button-link" href="/impor-data-historis">Kembali ke impor data</a>
        </main>
        """,
    )


def _render_success(operation: DailyOperation) -> str:
    mode_labels = {
        "transport": "Angkut",
        "lifting": "Lifting",
        "transport_and_lifting": "Angkut dan lifting",
    }
    source_labels = {"manual": "Input manual", "routing_provider": "Penyedia rute"}
    lifting = (
        f"<dt>Jam lifting</dt><dd>{_format_decimal(operation.lifting_hours)} jam</dd>"
        if operation.lifting_hours is not None
        else ""
    )
    stops = ""
    if operation.stop_sequence:
        stop_items = "".join(f"<li>{escape(stop)}</li>" for stop in operation.stop_sequence)
        stops = f'<dt>Urutan pemberhentian</dt><dd><ol class="stop-list">{stop_items}</ol></dd>'
    fallback = (
        '<p class="route-warning">Penyedia rute tidak tersedia saat perencanaan. '
        "Jarak total manual dipakai untuk estimasi ini.</p>"
        if operation.route_distance_manual_fallback
        else ""
    )
    return _page(
        "Operasi berhasil dibuat",
        f"""
        <main class="shell success">
          <p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">OPERASI TERSIMPAN</p>
          <h1>Operasi harian berhasil dibuat</h1>
          <p class="lead">Gunakan ID ini untuk proses dan pencatatan berikutnya.</p>
          <p class="operation-id"><span>ID operasi</span><strong>{escape(operation.operation_id)}</strong></p>
          <dl>
            <dt>Kategori kendaraan</dt><dd>{escape(operation.vehicle_category.value)}</dd>
            <dt>Mode aktivitas</dt><dd>{mode_labels[operation.activity_mode.value]}</dd>
            {lifting}
            <dt>Jarak total</dt><dd>{_format_decimal(operation.total_distance_km)} km</dd>
            <dt>Sumber jarak</dt><dd>{source_labels[operation.distance_source.value]}</dd>
            {stops}
          </dl>
          {fallback}
          <form method="post" action="/operasi-harian/{escape(operation.operation_id)}/prediksi">
            <button type="submit">Buat estimasi kebutuhan BBM</button>
          </form>
          <p><a href="/">Buat operasi lain</a></p>
        </main>
        """,
    )


def _render_prediction_success(prediction: FuelPrediction) -> str:
    fallback = (
        '<p class="route-warning">Penyedia rute tidak tersedia saat perencanaan; '
        "prediksi ini memakai jarak total manual.</p>"
        if prediction.route_distance_manual_fallback
        else ""
    )
    return _page(
        "Estimasi kebutuhan bahan bakar",
        f"""
        <main class="shell success">
          <p class="success-mark" aria-hidden="true">✓</p>
          <p class="eyebrow">ESTIMASI PERENCANAAN</p>
          <h1>Estimasi kebutuhan bahan bakar</h1>
          <p class="lead">Estimasi ini dipelajari dari catatan <em>bahan bakar disiapkan</em>.
            Nilai ini bukan konsumsi aktual yang telah diverifikasi.</p>
          <dl>
            <dt>ID operasi</dt><dd>{escape(prediction.operation_id)}</dd>
            <dt>Estimasi kebutuhan BBM</dt><dd>{_format_decimal(prediction.estimated_fuel_requirement_liters)} L</dd>
            <dt>Alokasi rekomendasi</dt><dd>{_format_decimal(prediction.recommended_allocation_liters)} L</dd>
            <dt>Rentang ketidakpastian</dt><dd>{_format_decimal(prediction.uncertainty_lower_liters)}–{_format_decimal(prediction.uncertainty_upper_liters)} L</dd>
            <dt>Sumber jarak rute</dt><dd>{escape(prediction.route_distance_source.value)}</dd>
            <dt>Model</dt><dd>{escape(prediction.model.model_version_id)} · {escape(prediction.model.algorithm)}</dd>
            <dt>Versi dataset</dt><dd>{escape(prediction.model.dataset_version_id)}</dd>
            <dt>Versi fitur</dt><dd>{escape(prediction.model.feature_version)}</dd>
          </dl>
          {fallback}
          <p class="lead">{escape(prediction.safety_policy)}</p>
          <a class="button-link" href="/">Buat operasi lain</a>
        </main>
        """,
    )


def _option(value: str, label: str, selected_value: str) -> str:
    selected = " selected" if value == selected_value else ""
    return f'<option value="{escape(value)}"{selected}>{escape(label)}</option>'


def _render_stop_input(value: str, index: int) -> str:
    number = index + 1
    return f"""
      <div class="stop-row">
        <label>Pemberhentian <input name="stop_sequence" type="text" value="{escape(value)}"
          autocomplete="off"></label>
        <div class="stop-controls">
          <button type="button" data-action="up" aria-label="Naikkan urutan pemberhentian {number}">↑</button>
          <button type="button" data-action="down" aria-label="Turunkan urutan pemberhentian {number}">↓</button>
          <button type="button" data-action="remove" aria-label="Hapus pemberhentian {number}">Hapus pemberhentian</button>
        </div>
      </div>
    """


def _format_decimal(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _page(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Fuel Predictor</title>
  <style>
    :root {{ color-scheme: light; --ink:#17251f; --muted:#5d6b64; --paper:#f4f1e8;
      --card:#fffdf7; --green:#185c43; --line:#d8d5ca; --danger:#9f2f2f; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:linear-gradient(145deg,#e6eee6,var(--paper) 55%);
      font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; min-height:100vh; }}
    .shell {{ width:min(680px,calc(100% - 32px)); margin:48px auto; padding:clamp(24px,5vw,48px);
      background:var(--card); border:1px solid rgba(23,37,31,.12); border-radius:24px;
      box-shadow:0 22px 60px rgba(31,49,40,.12); }}
    .eyebrow {{ color:var(--green); font-size:.78rem; font-weight:800; letter-spacing:.14em; }}
    h1 {{ margin:.25rem 0 .5rem; font:700 clamp(2rem,6vw,3.2rem)/1.05 Georgia,serif; }}
    .lead {{ margin:0 0 2rem; color:var(--muted); }}
    fieldset {{ padding:0; border:0; }} legend {{ font-size:1.2rem; font-weight:750; margin-bottom:1.2rem; }}
    .field {{ display:grid; gap:.4rem; margin-bottom:1.25rem; }} label {{ font-weight:700; }}
    .stops-field {{ margin:0 0 1.25rem; }} .hint {{ color:var(--muted); margin-top:-.5rem; }}
    .stop-row {{ display:flex; gap:.6rem; align-items:end; margin:.6rem 0; }} .stop-row label {{ flex:1; }}
    .stop-controls {{ display:flex; gap:.3rem; }} .stop-controls button,.secondary-button {{ width:auto;
      padding:.5rem .65rem; background:#e5eee8; color:var(--ink); border:1px solid var(--line); border-radius:8px; }}
    .secondary-button {{ margin-top:.4rem; }} .stop-list {{ display:inline-grid; gap:.15rem; margin:0; padding-left:1.2rem; text-align:left; }}
    .route-warning {{ margin:-1rem 0 1.5rem; padding:.8rem 1rem; border-left:4px solid #a86d10; background:#fff5db; }}
    .demo-note,.next-step {{ margin:0 0 1.5rem; padding:1rem 1.2rem; border-left:4px solid var(--green); background:#edf4ee; border-radius:8px; }}
    .next-step h2 {{ margin:0 0 .4rem; font-size:1.15rem; }} .next-step p {{ margin:.4rem 0 1rem; }}
    input,select {{ width:100%; min-height:48px; padding:.7rem .8rem; border:1px solid var(--line);
      border-radius:10px; color:var(--ink); background:white; font:inherit; }}
    input:focus,select:focus,button:focus,a:focus {{ outline:3px solid rgba(24,92,67,.25); outline-offset:2px; }}
    small {{ color:var(--muted); }} .unit-input {{ position:relative; }} .unit-input input {{ padding-right:4rem; }}
    .unit-input span {{ position:absolute; right:1rem; top:.75rem; color:var(--muted); }}
    button,.button-link {{ display:inline-flex; justify-content:center; width:100%; padding:.85rem 1.2rem;
      border:0; border-radius:12px; background:var(--green); color:white; font:700 1rem/1.4 inherit;
      text-decoration:none; cursor:pointer; }}
    .errors {{ margin:0 0 1.5rem; padding:1rem 1.2rem; border-left:4px solid var(--danger);
      border-radius:8px; background:#fff0ee; }} .errors h2 {{ margin:0; font-size:1.05rem; }}
    .errors ul {{ margin:.5rem 0 0; padding-left:1.2rem; }} [hidden] {{ display:none !important; }}
    .success-mark {{ display:grid; place-items:center; width:48px; height:48px; border-radius:50%;
      background:#dff1e5; color:var(--green); font-size:1.6rem; font-weight:900; }}
    .operation-id {{ display:grid; gap:.25rem; margin:1.5rem 0; padding:1rem; border-radius:12px;
      background:#edf4ee; }} .operation-id span,dt {{ color:var(--muted); font-size:.88rem; }}
    .operation-id strong {{ overflow-wrap:anywhere; font-size:1.05rem; }}
    dl {{ display:grid; grid-template-columns:1fr 1fr; gap:.6rem 1.5rem; margin:0 0 2rem; }}
    dt,dd {{ margin:0; padding:.45rem 0; border-bottom:1px solid var(--line); }} dd {{ text-align:right; }}
    @media (max-width:520px) {{ .shell {{ margin:16px auto; }} dl {{ grid-template-columns:1fr; gap:0; }}
      dd {{ text-align:left; padding-top:0; }} }}
  </style>
</head>
<body>{content}</body>
</html>"""
