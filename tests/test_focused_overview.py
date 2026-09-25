"""Entry pages summarize work and link to the details instead of duplicating them."""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app


def test_overview_links_to_details_without_repeating_their_tables(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        overview = client.get("/")
        assert overview.status_code == 200
        main = overview.text.split('<main ', 1)[1]
        assert '<table' not in main
        for destination in (
            "/prediksi",
            "/bahan-bakar-aktual",
            "/prediksi-operasi-massal",
            "/pemantauan/kesehatan-sistem",
            "/pengelolaan-model",
            "/pemantauan/kinerja-model",
            "/pemantauan/pergeseran-data",
        ):
            assert f'href="{destination}"' in main
            assert client.get(destination).status_code == 200
        # A compact overview must still disclose absent monitoring data.
        assert "belum pernah berhasil" in main
        assert "Cadangan data" not in main
        assert "Cadangan data" in client.get("/pemantauan/kesehatan-sistem").text


def test_prediction_keeps_actions_visible_before_optional_comparisons(tmp_path: Path) -> None:
    from tests.test_actual_fuel_outcomes import _train_baseline

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        response = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "vehicle": "Prime Mover",
                "activity_mode": "transport",
                "total_distance_km": "50",
                "distance_source": "manual",
            },
        )
    assert response.status_code == 201, response.text
    html = response.text
    fold_start = html.rindex('<details')
    fold_tag = html[fold_start:html.index('>', fold_start)]
    assert "open" not in fold_tag
    assert "Operasi serupa sebelumnya" in html[fold_start:]
    assert html.index("Catat BBM aktual untuk operasi ini") < fold_start
    assert "Rentang ketidakpastian" in html[:fold_start]
    assert "bukan konsumsi aktual" in html[:fold_start]
