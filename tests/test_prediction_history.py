"""Yesterday's estimate can be found again.

Until now an estimate existed only on the page shown right after it was made.
Close the tab and the number was gone from the interface - it was in the
database, but nothing listed it. The history page lists recent predictions,
newest first, says whether actual fuel has been reported for each, and every
operation has a page of its own.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _operation_with_prediction, _train_baseline


def test_history_lists_predictions_newest_first_with_their_actual_status(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        older = _operation_with_prediction(client, 24)["operation"]["operation_id"]
        newer = _operation_with_prediction(client, 36)["operation"]["operation_id"]
        client.post(
            f"/api/v1/daily-operations/{older}/actual-fuel",
            json={"actual_fuel_liters": 22.5, "measurement_source": "fuel_meter"},
        )

        page = client.get("/riwayat-prediksi")

    assert page.status_code == 200
    assert page.text.index(newer) < page.text.index(older)
    assert f'href="/operasi-harian/{newer}"' in page.text
    # The one without an actual offers to record it; the other shows the figure.
    assert f'href="/bahan-bakar-aktual?operation_id={newer}"' in page.text
    assert f'href="/bahan-bakar-aktual?operation_id={older}"' not in page.text
    assert "22,5" in page.text


def test_history_says_so_when_nothing_has_been_predicted(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        page = client.get("/riwayat-prediksi")

    assert page.status_code == 200
    assert "Belum ada prediksi" in page.text


def test_every_operation_has_its_own_estimate_page(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        item = _operation_with_prediction(client, 24)
        operation_id = item["operation"]["operation_id"]
        recommended = item["prediction"]["recommended_allocation_liters"]

        page = client.get(f"/operasi-harian/{operation_id}")
        missing = client.get("/operasi-harian/OPR-TIDAK-ADA")

    assert page.status_code == 200
    assert "Estimasi kebutuhan bahan bakar" in page.text
    assert operation_id in page.text
    assert f"{recommended:.2f}".replace(".", ",").rstrip("0").rstrip(",") in page.text
    # Reopening is not making: no "berhasil dibuat" banner on a lookup.
    assert "Estimasi berhasil dibuat" not in page.text
    assert missing.status_code == 404


def test_an_operation_saved_without_a_model_has_a_page_that_offers_the_estimate(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        operation = client.post(
            "/api/v1/daily-operations",
            json={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport",
                "total_distance_km": 12,
                "distance_source": "manual",
            },
        ).json()

        page = client.get(f"/operasi-harian/{operation['operation_id']}")

    assert page.status_code == 200
    assert "Operasi harian tersimpan" in page.text
    assert "Buat estimasi kebutuhan BBM" in page.text


def test_history_can_reach_further_back_on_request(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        ids = [
            _operation_with_prediction(client, 20 + i)["operation"]["operation_id"]
            for i in range(3)
        ]

        default_page = client.get("/riwayat-prediksi?jumlah=2").text
        wider_page = client.get("/riwayat-prediksi?jumlah=10").text

    assert ids[0] not in default_page and ids[2] in default_page
    assert 'href="/riwayat-prediksi?jumlah=8"' in default_page
    assert all(operation_id in wider_page for operation_id in ids)
