"""Refreshing the page after planning does not plan the operation again.

The estimate was the answer to the form's POST, so a refresh on a phone -
or reopening the tab - asked the browser to send the form again, and a
second operation with its own code (…-2) was planned. Saving now redirects
to the operation's own page, which a refresh simply reloads.
"""

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from httpx import Response

from fuel_predictor.main import create_app
from tests.test_actual_fuel_outcomes import _train_baseline

_FORM = {"content-type": "application/x-www-form-urlencoded"}
_PLAN = urlencode(
    [
        ("vehicle_category", "ANGBER"),
        ("activity_mode", "transport"),
        ("total_distance_km", "40"),
        ("distance_source", "manual"),
    ]
)


def _waiting(client: TestClient) -> int:
    """Operations planned and waiting for actual fuel, as Catat Aktual lists them."""
    page: str = client.get("/bahan-bakar-aktual").text
    return page.count('href="/bahan-bakar-aktual?operation_id=')


def test_saving_redirects_to_the_operation_and_a_refresh_plans_nothing(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        saved = client.post("/operasi-harian", content=_PLAN, headers=_FORM, follow_redirects=False)
        location = saved.headers["location"]
        shown = client.get(location)
        refreshed = client.get(location)
        waiting = _waiting(client)

    assert saved.status_code == 303
    assert location.startswith("/operasi-harian/") and location.endswith("?dibuat=1")
    assert shown.status_code == 200
    assert "Estimasi berhasil dibuat" in shown.text
    assert "Alokasi rekomendasi" in shown.text
    # Reloading reads the same operation; nothing new is planned.
    assert refreshed.status_code == 200
    assert waiting == 1


def test_the_operation_page_without_the_flag_says_nothing_about_creating(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        location = client.post(
            "/operasi-harian", content=_PLAN, headers=_FORM, follow_redirects=False
        ).headers["location"]
        later = client.get(location.split("?")[0])

    assert "Estimasi berhasil dibuat" not in later.text


def test_without_a_model_the_redirected_page_says_why_there_is_no_estimate(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        saved = client.post("/operasi-harian", content=_PLAN, headers=_FORM)

    assert saved.status_code == 200
    assert "Operasi harian tersimpan" in saved.text
    assert "belum ada model aktif" in saved.text.lower()


def test_a_refused_form_is_still_answered_in_place(tmp_path: Path) -> None:
    """Only a saved operation redirects; a form to correct comes back as is."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        refused = client.post(
            "/operasi-harian",
            content=urlencode([("vehicle_category", "ANGBER"), ("distance_source", "manual")]),
            headers=_FORM,
            follow_redirects=False,
        )

    assert refused.status_code == 422


_SHEET = b"Kendaraan,Aktivitas (wajib),Jarak Total (km) (wajib)\n,Mobilisasi,30\n,Mobilisasi,45\n"


def _upload(client: TestClient, content: bytes = _SHEET) -> Response:
    response: Response = client.post(
        "/prediksi-operasi-massal",
        files={"file": ("rencana.csv", content, "text/csv")},
        follow_redirects=False,
    )
    return response


def test_a_bulk_plan_leads_to_its_result_and_sending_it_again_plans_nothing(
    tmp_path: Path,
) -> None:
    """Refreshing the result page, or a double tap, sent the whole file again
    and planned every row twice."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        first = _upload(client)
        result = client.get(first.headers["location"])
        reloaded = client.get(first.headers["location"])
        again = _upload(client)
        repeated = client.get(again.headers["location"])
        waiting = _waiting(client)

    assert first.status_code == 303
    assert first.headers["location"].startswith("/prediksi-operasi-massal/hasil/")
    assert result.status_code == 200 and "2 operasi mendapat kode dan estimasi" in result.text
    assert reloaded.text.count("operation-code") == result.text.count("operation-code")
    # The same file again leads to the same result, said so, and plans nothing.
    assert again.headers["location"] == first.headers["location"] + "?ulang=1"
    assert "Berkas ini sudah diproses" in repeated.text
    assert waiting == 2


def test_a_changed_file_is_a_new_plan(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        first = _upload(client)
        second = _upload(client, _SHEET + b",Mobilisasi,60\n")
        waiting = _waiting(client)

    assert first.headers["location"] != second.headers["location"]
    assert waiting == 5


def test_a_result_is_its_uploader_s_and_a_forgotten_one_says_where_to_look(
    tmp_path: Path,
) -> None:
    from tests.test_two_roles import (
        _ADMIN,
        _OPERATOR,
        _csrf,
        _sign_in,
        _sign_out,
        _train_baseline_with_csrf,
    )

    app = create_app(database_path=tmp_path / "operations.sqlite3", bootstrap_administrator=_ADMIN)
    with TestClient(app) as client:
        _sign_in(client, *_ADMIN)
        client.post(
            "/api/v1/users",
            json={
                "username": _OPERATOR[0],
                "full_name": "Andi",
                "password": _OPERATOR[1],
                "role": "operator",
            },
        )
        _train_baseline_with_csrf(client)
        token = _csrf(client.get("/prediksi-operasi-massal").text)
        location = client.post(
            "/prediksi-operasi-massal",
            data={"csrf_token": token},
            files={"file": ("rencana.csv", _SHEET, "text/csv")},
            follow_redirects=False,
        ).headers["location"]
        _sign_out(client)
        _sign_in(client, *_OPERATOR)
        someone_else = client.get(location)
        unknown = client.get("/prediksi-operasi-massal/hasil/tidak-ada")

    assert someone_else.status_code == 404
    assert "tidak lagi tersedia" in someone_else.text
    assert "Riwayat Prediksi" in unknown.text


def test_an_actual_fuel_sheet_leads_to_its_result_too(tmp_path: Path) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        _train_baseline(client)
        location = client.post(
            "/operasi-harian", content=_PLAN, headers=_FORM, follow_redirects=False
        ).headers["location"]
        code = location.split("/")[2].split("?")[0]
        sheet = f"Kode Operasi (wajib),Bahan Bakar Aktual (L) (wajib)\n{code},31\n".encode()
        sent = client.post(
            "/bahan-bakar-aktual-massal",
            files={"file": ("aktual.csv", sheet, "text/csv")},
            follow_redirects=False,
        )
        result = client.get(sent.headers["location"])
        again = client.post(
            "/bahan-bakar-aktual-massal",
            files={"file": ("aktual.csv", sheet, "text/csv")},
            follow_redirects=False,
        )

    assert sent.status_code == 303
    assert sent.headers["location"].startswith("/bahan-bakar-aktual-massal/hasil/")
    assert result.status_code == 200 and "31" in result.text
    assert again.headers["location"] == sent.headers["location"] + "?ulang=1"


_HISTORY = (
    b"Kategori ANGBER,Mode Aktivitas,Jam Lifting,Jarak Total (km),"
    b"Bahan Bakar Disiapkan (L),Sumber Jarak\n"
    b"ANGBER,transport,,20,18,manual\n"
    b"ANGBER,transport,,40,28,manual\n"
    b"ANGBER,lifting,2,20,25,manual\n"
)


def test_the_same_history_again_is_not_a_second_dataset_and_training_lands_on_models(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        first = client.post(
            "/impor-data-historis",
            files={"file": ("riwayat.csv", _HISTORY, "text/csv")},
            follow_redirects=False,
        )
        imported = client.get(first.headers["location"])
        again = client.post(
            "/impor-data-historis",
            files={"file": ("riwayat.csv", _HISTORY, "text/csv")},
            follow_redirects=False,
        )
        second_dataset = client.get("/api/v1/dataset-versions/DSV-000002/daily-operations")
        trained = client.post(
            "/dataset-versions/DSV-000001/latih-kandidat-baseline", follow_redirects=False
        )
        models = client.get(trained.headers["location"])

    assert first.status_code == 303 and imported.status_code == 200
    assert again.headers["location"] == first.headers["location"] + "?ulang=1"
    assert "DSV-000001" in imported.text
    assert second_dataset.status_code == 404
    assert trained.status_code == 303
    assert trained.headers["location"].startswith("/pengelolaan-model?dilatih=MDL-")
    assert "dilatih" in models.text and "bandingkan lalu promosikan" in models.text
