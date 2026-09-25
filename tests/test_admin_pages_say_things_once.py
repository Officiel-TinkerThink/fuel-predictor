"""The administrator's pages say each thing once, in words.

Kinerja Model repeated the one model's numbers as "all models"; Pergeseran
Data said "not enough data" in a banner, a tile and a card; empty lists
offered a search box; the audit trail showed "fuel_meter", "47.0" and an
OPR- id where the pages say "Meter BBM", "47" and the operation's code.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_one_model_s_numbers_are_not_repeated_as_all_models(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        client.post(
            f"/api/v1/daily-operations/{operation['operation_id']}/actual-fuel",
            json={"actual_fuel_liters": 21, "measurement_source": "fuel_meter"},
        )
        page = client.get("/pemantauan/kinerja-model").text

    main = page.split("<main ", 1)[1]
    assert "<h2>Per model</h2>" in main
    assert "Semua prediksi, semua model" not in main
    assert "Degradasi per kategori" not in main
    # The sidebar already links these pages.
    assert ">Kelola model</a>" not in main


def test_drift_without_data_says_so_once(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        main = client.get("/pemantauan/pergeseran-data").text.split("<main ", 1)[1]

    assert main.count("Belum dihitung") == 1
    assert "Belum tersedia" not in main
    assert "Ciri operasi yang bergeser" not in main


def test_an_empty_list_offers_its_first_step_not_a_search_box(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        empty = client.get("/model/riwayat").text.split("<main ", 1)[1]
        searched = client.get("/model/riwayat?cari=tidak-ada").text.split("<main ", 1)[1]

    assert 'role="search"' not in empty
    assert 'href="/model/unggah"' in empty
    # A search that found nothing keeps its box, so it can be changed.
    assert 'role="search"' in searched


def test_the_audit_trail_speaks_the_pages_words(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        operation = _operation_with_prediction(client, 24)["operation"]
        client.post(
            "/bahan-bakar-aktual",
            data={
                "operation_id": operation["operation_code"],
                "actual_fuel_liters": "47",
                "measurement_source": "fuel_meter",
            },
        )
        audit = client.get("/audit").text.split("<main ", 1)[1]

    recorded = audit.split("BBM aktual dicatat", 1)[1].split("</tr>", 1)[0]
    assert f'<code class="operation-code">{operation["operation_code"]}</code>' in recorded
    assert '<span class="hint">diukur dengan:</span> Meter BBM' in recorded
    assert '<span class="hint">liter:</span> 47</li>' in recorded
    assert "fuel_meter" not in recorded.replace("actual_fuel_recorded", "")
