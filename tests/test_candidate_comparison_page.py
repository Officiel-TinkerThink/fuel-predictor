"""Deciding on a candidate model is a comparison, and the page reads as one.

The old page listed the candidate's MAE and the active model's MAE as two
detail rows and left the arithmetic to the reader. A manager deciding
whether to promote wants the verdict first - better, worse, or not yet
knowable - then the numbers side by side, then the button. And promotion,
which changes every estimate made from then on, asks once before it acts.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_manual_model_promotion import _operation_with_actual, _train_candidate

_ROWS = [
    "ANGBER,transport,,20,18,manual",
    "ANGBER,transport,,40,28,manual",
    "ANGBER,lifting,2,20,25,manual",
]


def test_comparison_says_it_cannot_judge_without_actual_fuel(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        candidate = _train_candidate(client, "first.csv", _ROWS)["model_version_id"]

        page = client.get(f"/kandidat-model/{candidate}/perbandingan")

    assert page.status_code == 200
    assert "Belum bisa dibandingkan" in page.text
    assert "Promosikan" in page.text


def test_comparison_leads_with_a_verdict_and_shows_both_models_side_by_side(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        first = _train_candidate(client, "first.csv", _ROWS)["model_version_id"]
        client.post(f"/api/v1/model-candidates/{first}/promote")
        _operation_with_actual(client, 24)
        _operation_with_actual(client, 36)
        second = _train_candidate(client, "second.csv", _ROWS)["model_version_id"]

        page = client.get(f"/kandidat-model/{second}/perbandingan")

    assert page.status_code == 200
    assert "Kandidat" in page.text and "Model aktif" in page.text
    assert first in page.text and second in page.text
    # A verdict banner, one of the three outcomes.
    assert any(
        phrase in page.text
        for phrase in ("Kandidat lebih tepat", "Kandidat kurang tepat", "Sama tepatnya")
    )
    # Metrics are named in plain words, as on Kinerja Model.
    assert "Selisih rata-rata (MAE)" in page.text
    # Promotion confirms before acting.
    assert "<dialog" in page.text
