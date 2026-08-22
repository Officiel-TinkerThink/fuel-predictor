from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from fuel_predictor.main import create_app

_HISTORICAL_HEADERS = ",".join(
    [
        "Kategori ANGBER",
        "Mode Aktivitas",
        "Jam Operasi Lifting",
        "Jarak Total (km)",
        "Bahan Bakar Disiapkan (L)",
        "Sumber Jarak",
    ]
)
_HISTORICAL_HEADERS_WITH_SHORT_LIFTING = _HISTORICAL_HEADERS.replace(
    "Jam Operasi Lifting", "Jam Lifting"
)


def test_api_imports_valid_csv_rows_and_quarantines_invalid_rows_with_provenance(
    tmp_path: Path,
) -> None:
    source = (
        f"{_HISTORICAL_HEADERS}\n"
        'angber,transport_and_lifting,"2,5",86.4,45,manual\n'
        ",,,,,\n"
        "ANGBER,transport,tidak ada,60,34,manual\n"
        "ANGBER,transport,,0,23,manual\n"
    )

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat-angber.csv", source.encode(), "text/csv")},
        )

    assert response.status_code == 201
    result = response.json()
    assert result["dataset_version"] == {
        "dataset_version_id": "DSV-000001",
        "version": 1,
        "source_filename": "riwayat-angber.csv",
        "valid_operation_count": 1,
        "quarantined_row_count": 2,
        "ignored_blank_row_count": 1,
    }
    assert result["valid_operations"] == [
        {
            "vehicle_category": "ANGBER",
            "activity_mode": "transport_and_lifting",
            "lifting_hours": 2.5,
            "total_distance_km": 86.4,
            "distance_source": "manual",
            "prepared_fuel_liters": 45.0,
            "source": {
                "sheet_name": "CSV",
                "row_number": 2,
                "original_headers": {"lifting_hours": "Jam Operasi Lifting"},
                "raw_values": {
                    "Kategori ANGBER": "angber",
                    "Mode Aktivitas": "transport_and_lifting",
                    "Jam Operasi Lifting": "2,5",
                    "Jarak Total (km)": "86.4",
                    "Bahan Bakar Disiapkan (L)": "45",
                    "Sumber Jarak": "manual",
                },
            },
        }
    ]
    assert result["correction_report"] == [
        {
            "sheet_name": "CSV",
            "row_number": 4,
            "reasons": [{"field": "lifting_hours", "message": "Jam lifting harus berupa angka."}],
            "raw_values": {
                "Kategori ANGBER": "ANGBER",
                "Mode Aktivitas": "transport",
                "Jam Operasi Lifting": "tidak ada",
                "Jarak Total (km)": "60",
                "Bahan Bakar Disiapkan (L)": "34",
                "Sumber Jarak": "manual",
            },
        },
        {
            "sheet_name": "CSV",
            "row_number": 5,
            "reasons": [
                {"field": "total_distance_km", "message": "Jarak total harus lebih besar dari 0."}
            ],
            "raw_values": {
                "Kategori ANGBER": "ANGBER",
                "Mode Aktivitas": "transport",
                "Jam Operasi Lifting": "",
                "Jarak Total (km)": "0",
                "Bahan Bakar Disiapkan (L)": "23",
                "Sumber Jarak": "manual",
            },
        },
    ]


def test_api_accepts_xlsx_sheets_and_creates_a_new_version_when_corrected_data_is_reimported(
    tmp_path: Path,
) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Juli 2026"
    worksheet.append(
        [
            "Kategori ANGBER",
            "Mode Aktivitas",
            "Lifting Hours",
            "Jarak Total (km)",
            "Bahan Bakar Disiapkan (L)",
            "Sumber Jarak",
        ]
    )
    worksheet.append(["ANGKUTAN BERAT", "lifting", 3, 25, 20, "routing_provider"])
    workbook_bytes = BytesIO()
    workbook.save(workbook_bytes)

    corrected_csv = f"{_HISTORICAL_HEADERS_WITH_SHORT_LIFTING}\nANGBER,transport,,42,32,manual\n"

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        xlsx_response = client.post(
            "/api/v1/historical-datasets",
            files={
                "file": (
                    "riwayat.xlsx",
                    workbook_bytes.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        corrected_response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("riwayat-dikoreksi.csv", corrected_csv.encode(), "text/csv")},
        )
        retained_rows = client.get("/api/v1/dataset-versions/DSV-000002/daily-operations")

    assert xlsx_response.status_code == 201
    assert xlsx_response.json()["valid_operations"][0]["source"] == {
        "sheet_name": "Juli 2026",
        "row_number": 2,
        "original_headers": {"lifting_hours": "Lifting Hours"},
        "raw_values": {
            "Kategori ANGBER": "ANGKUTAN BERAT",
            "Mode Aktivitas": "lifting",
            "Lifting Hours": 3,
            "Jarak Total (km)": 25,
            "Bahan Bakar Disiapkan (L)": 20,
            "Sumber Jarak": "routing_provider",
        },
    }
    assert corrected_response.status_code == 201
    assert corrected_response.json()["dataset_version"]["dataset_version_id"] == "DSV-000002"
    assert retained_rows.status_code == 200
    assert retained_rows.json()["valid_operations"] == corrected_response.json()["valid_operations"]


def test_api_ignores_precreated_calendar_rows_that_only_contain_a_date(tmp_path: Path) -> None:
    source = f"Tanggal,{_HISTORICAL_HEADERS_WITH_SHORT_LIFTING}\n2026-07-01,,,,,,\n"

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("kalender.csv", source.encode(), "text/csv")},
        )

    assert response.status_code == 201
    assert response.json()["dataset_version"]["valid_operation_count"] == 0
    assert response.json()["dataset_version"]["ignored_blank_row_count"] == 1
    assert response.json()["correction_report"] == []


def test_api_reports_each_missing_required_header_once_for_correction(tmp_path: Path) -> None:
    source = """Kategori ANGBER,Mode Aktivitas,Jarak Total (km),Bahan Bakar Disiapkan (L)
ANGBER,transport,30,20
"""

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        response = client.post(
            "/api/v1/historical-datasets",
            files={"file": ("tanpa-sumber.csv", source.encode(), "text/csv")},
        )

    assert response.status_code == 201
    assert response.json()["correction_report"] == [
        {
            "sheet_name": "CSV",
            "row_number": 2,
            "reasons": [
                {"field": "distance_source", "message": "Kolom Sumber jarak tidak ditemukan."}
            ],
            "raw_values": {
                "Kategori ANGBER": "ANGBER",
                "Mode Aktivitas": "transport",
                "Jarak Total (km)": "30",
                "Bahan Bakar Disiapkan (L)": "20",
            },
        }
    ]


def test_indonesian_upload_form_shows_dataset_summary_and_correction_guidance(
    tmp_path: Path,
) -> None:
    source = (
        f"{_HISTORICAL_HEADERS_WITH_SHORT_LIFTING}\n"
        "ANGBER,transport,,30,20,manual\n"
        "ANGBER,lifting,,30,20,manual\n"
    )

    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        form = client.get("/impor-data-historis")
        response = client.post(
            "/impor-data-historis",
            files={"file": ("riwayat.csv", source.encode(), "text/csv")},
        )

    assert form.status_code == 200
    assert "Impor Data Historis ANGBER" in form.text
    assert response.status_code == 201
    assert "Dataset versi 1 berhasil dibuat" in response.text
    assert "1 operasi valid siap digunakan untuk pelatihan" in response.text
    assert "1 baris dikarantina" in response.text
    assert "Jam lifting harus lebih besar dari 0" in response.text


def test_demo_flow_downloads_imports_and_manually_trains_the_baseline(tmp_path: Path) -> None:
    """The friend-demo path stays entirely in the Indonesian browser interface."""
    with TestClient(create_app(database_path=tmp_path / "operations.sqlite3")) as client:
        sample = client.get("/contoh-data-riwayat.csv")
        imported = client.post(
            "/impor-data-historis",
            files={"file": ("riwayat-angber-demo.csv", sample.content, "text/csv")},
        )
        trained = client.post("/dataset-versions/DSV-000001/latih-kandidat-baseline")
        model_version_id = trained.text.split("<dt>ID model</dt><dd>", 1)[1].split("</dd>", 1)[0]
        promoted = client.post(f"/kandidat-model/{model_version_id}/promosikan")
        operation = client.post(
            "/operasi-harian",
            data={
                "vehicle_category": "ANGBER",
                "activity_mode": "transport_and_lifting",
                "lifting_hours": "2",
                "total_distance_km": "54",
                "distance_source": "manual",
            },
        )
        operation_id = operation.text.split("<strong>", 1)[1].split("</strong>", 1)[0]
        prediction = client.post(f"/operasi-harian/{operation_id}/prediksi")

    assert sample.status_code == 200
    assert "Bahan Bakar Disiapkan (L)" in sample.text
    assert imported.status_code == 201
    assert "Latih kandidat baseline secara manual" in imported.text
    assert trained.status_code == 201
    assert "Kandidat baseline siap digunakan" in trained.text
    assert "MDL-" in trained.text
    assert promoted.status_code == 200
    assert "Model aktif diperbarui" in promoted.text
    assert operation.status_code == 201
    assert prediction.status_code == 201
    assert "Estimasi kebutuhan bahan bakar" in prediction.text
    assert "Alokasi rekomendasi" in prediction.text
    assert "bukan konsumsi aktual" in prediction.text
