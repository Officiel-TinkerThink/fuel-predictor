# ruff: noqa: E501

from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response

from fuel_predictor.application.baseline_predictions import (
    BaselineTrainingError,
    TrainBaselineCandidate,
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
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.prediction import ModelVersion

_UPLOAD_FILE = File(...)
_DEMO_HISTORICAL_DATA = Path(__file__).resolve().parents[3] / "examples" / "riwayat-angber-demo.csv"


def build_form_router(
    import_historical_dataset: ImportHistoricalDataset,
    train_baseline_candidate: TrainBaselineCandidate,
    promote_candidate_model: PromoteCandidateModel,
    get_candidate_model_comparison: GetCandidateModelComparison,
    get_model_governance_dashboard: GetModelGovernanceDashboard,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    def _current_csrf(request: Request) -> str:
        caller = guard.caller_or_none(request)
        return caller.csrf_token if caller is not None else ""

    @router.get("/impor-data-historis", response_class=HTMLResponse)
    def show_import_form(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_import_form(_current_csrf(request)))

    @router.get("/contoh-data-riwayat.csv")
    def download_demo_historical_data() -> Response:
        return Response(
            content=_DEMO_HISTORICAL_DATA.read_bytes(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="riwayat-angber-demo.csv"'},
        )

    @router.get("/pengelolaan-model", response_class=HTMLResponse)
    def show_model_governance(request: Request) -> HTMLResponse:
        return HTMLResponse(
            _render_model_governance(
                get_model_governance_dashboard.execute(), _current_csrf(request)
            )
        )

    @router.get("/kandidat-model/{model_version_id}/perbandingan", response_class=HTMLResponse)
    def show_candidate_comparison(model_version_id: str, request: Request) -> HTMLResponse:
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
        return HTMLResponse(_render_candidate_comparison(comparison, _current_csrf(request)))

    @router.post("/impor-data-historis", response_class=HTMLResponse)
    async def submit_import(request: Request, file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        try:
            result = import_historical_dataset.execute(
                file.filename or "berkas-impor", await file.read()
            )
        except HistoricalDatasetImportError as error:
            return HTMLResponse(
                _render_import_form(_current_csrf(request), error.message),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return HTMLResponse(
            _render_import_success(result, _current_csrf(request)),
            status_code=status.HTTP_201_CREATED,
        )

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

    return router


def _csrf_input(csrf_token: str) -> str:
    return f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'


def _metric(value: float | None, unit: str) -> str:
    return "Belum cukup data" if value is None else f"{_format_decimal(value)} {unit}"


def _render_model_governance(dashboard: Any, csrf_token: str) -> str:
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
            f'<td><form method="post" action="/kandidat-model/{escape(candidate.model_version_id)}/promosikan">{_csrf_input(csrf_token)}<button>Promosikan manual</button></form></td>'
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


def _render_candidate_comparison(comparison: Any, csrf_token: str) -> str:
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
          <form method="post" action="/kandidat-model/{escape(comparison.candidate.model_version_id)}/promosikan">{_csrf_input(csrf_token)}<button>Promosikan kandidat secara manual</button></form>
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


def _render_import_form(csrf_token: str, error: str | None = None) -> str:
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
            {_csrf_input(csrf_token)}
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




def _render_import_success(result: HistoricalDatasetImportResult, csrf_token: str) -> str:
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
              {_csrf_input(csrf_token)}
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


def _option(value: str, label: str, selected_value: str) -> str:
    selected = " selected" if value == selected_value else ""
    return f'<option value="{escape(value)}"{selected}>{escape(label)}</option>'


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
