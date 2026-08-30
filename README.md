# Fuel Predictor

> Picking this project up for the first time, or handing it to someone (or something) else?
> Start with [HANDOFF.md](HANDOFF.md).

Fondasi MVP lokal untuk mencatat satu **Daily Operation** ANGBER melalui form berbahasa
Indonesia atau API FastAPI. Kedua jalur menggunakan aturan pembuatan yang sama dan menyimpan
operasi serta dataset historis di PostgreSQL.

## Demo cepat (bahasa Indonesia)

Alur paling singkat untuk menunjukkan aplikasi ke teman: impor riwayat contoh, **latih kandidat
baseline secara manual**, buat operasi, lalu tampilkan hasil estimasi. Aplikasi juga mendukung
pencatatan bahan bakar aktual, evaluasi, pemantauan lokal, dan promosi model yang tetap manual.

Jalankan dengan Docker (paling praktis karena PostgreSQL ikut disiapkan):

```powershell
Copy-Item .env.example .env
# Ganti POSTGRES_PASSWORD di .env dengan nilai lokal.
docker compose up --build
```

Atau jalankan lokal bila PostgreSQL 16 dan Python 3.12+ sudah tersedia:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Atur FUEL_PREDICTOR_DATABASE_URL di .env, lalu:
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn fuel_predictor.main:app --reload
```

Buka [http://127.0.0.1:8000/](http://127.0.0.1:8000/) lalu:

1. Pilih **Impor data historis ANGBER**, unduh **data contoh yang siap diimpor**, dan unggah CSV itu.
2. Pada ringkasan impor, tekan **Latih kandidat baseline secara manual**. Tidak ada promosi otomatis.
3. Tekan **Lanjut buat operasi dan estimasi**. Isi jarak manual, atau masukkan stop berurutan
   beserta jarak cadangan; tanpa kunci Google Maps aplikasi dengan jelas memakai fallback manual.
4. Simpan operasi, lalu tekan **Buat estimasi kebutuhan BBM**. Hasil menampilkan estimasi,
   alokasi rekomendasi, rentang ketidakpastian, sumber jarak, dan lineage model/dataset.
5. Setelah operasi selesai, buka **Catat BBM aktual**, masukkan ID operasi dan nilai aktual,
   lalu buka **Kinerja prediksi** untuk melihat MAE, RMSE, sMAPE, serta cakupan interval.
6. Buka **Pemantauan Operasi dan Alert** untuk melihat isu kualitas data, aktual yang terlambat,
   drift fitur, serta tren/degradasi kesalahan. Alert hanya disimpan secara lokal dan tidak pernah
   mempromosikan model secara otomatis.

CSV contoh yang sama tersedia di [examples/riwayat-angber-demo.csv](examples/riwayat-angber-demo.csv).

## Struktur dan pilihan teknologi

Proyek ini sengaja tetap berupa **modular monolith**: form HTML berbahasa Indonesia dan API
FastAPI adalah dua antarmuka dari satu aplikasi, bukan dua layanan yang harus disinkronkan.
Kode dibagi berdasarkan tanggung jawab di `src/fuel_predictor/`: `domain` berisi aturan bisnis
murni, `application` menjalankan use case, `delivery` menangani API/form, dan
`infrastructure` mengimplementasikan PostgreSQL.

Pydantic dipakai untuk kontrak HTTP dan konfigurasi lingkungan. `DailyOperation` dan model
domain lain tetap berupa dataclass agar aturan bisnis tidak bergantung pada FastAPI, Pydantic,
atau ORM. SQLAlchemy menangani pemetaan/pooling database dan Alembic menangani evolusi skema;
tidak ada SQL koneksi atau pembuatan tabel buatan sendiri di jalur aplikasi.

## Menjalankan secara lokal

Prasyarat: Python 3.12 atau lebih baru dan PostgreSQL 16 atau lebih baru.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn fuel_predictor.main:app --reload
```

Buka `http://127.0.0.1:8000/` untuk form. Dokumentasi API interaktif tersedia di
`http://127.0.0.1:8000/docs`.

Secara default aplikasi membaca `FUEL_PREDICTOR_DATABASE_URL`; jika belum diatur, nilainya
adalah `postgresql+psycopg://fuel_predictor:fuel_predictor@localhost:5432/fuel_predictor`.
Simpan URL ini hanya di `.env` (lihat `.env.example`), bukan di source code.

Periksa dan terapkan skema sebelum menjalankan aplikasi di luar Compose:

```powershell
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe upgrade head
# Saat struktur data berubah:
.\.venv\Scripts\alembic.exe revision --autogenerate -m "jelaskan perubahan skema"
```

Tinjau setiap migrasi yang dihasilkan sebelum menerapkannya. Aplikasi produksi hanya memakai
skema yang dibuat Alembic; pembuatan skema langsung tersedia semata-mata untuk test terisolasi.

## Menjalankan dengan Docker

```powershell
Copy-Item .env.example .env
# Ubah POSTGRES_PASSWORD di .env.
docker compose up --build
```

Compose menjalankan PostgreSQL, menunggu health check, menerapkan migrasi Alembic, lalu
menjalankan aplikasi di `http://127.0.0.1:8000/`. Volume `postgres_data` menjaga data tetap ada
ketika container aplikasi dimulai ulang.

## Kontrak pembuatan API

`POST /api/v1/daily-operations`

```json
{
  "vehicle_category": "ANGBER",
  "activity_mode": "transport_and_lifting",
  "lifting_hours": 2.5,
  "total_distance_km": 86.4,
  "distance_source": "manual",
  "stop_sequence": ["Depo", "Site A", "Depo"]
}
```

Nilai `activity_mode` yang didukung:

- `transport`: `lifting_hours` harus kosong atau `null`;
- `lifting`: `lifting_hours` wajib lebih besar dari nol;
- `transport_and_lifting`: `lifting_hours` wajib lebih besar dari nol.

`stop_sequence` bersifat opsional agar operasi historis berbasis jarak tetap kompatibel. Bila
dikirim, urutan lokasi tersebut adalah otoritatif: penyedia rute menghitungnya tanpa optimasi
atau pengurutan ulang dan hasil jaraknya menggantikan `total_distance_km`. `total_distance_km`
tetap wajib sebagai cadangan manual bila penyedia tidak tersedia. Respons untuk operasi dengan
stop mencantumkan `route_distance_manual_fallback`; nilai `true` berarti prediksi memakai jarak
manual tersebut. Alias API `stops` juga diterima saat transisi.

Nilai `distance_source` yang didukung adalah `manual` dan `routing_provider`. Jarak total harus
lebih besar dari nol. Respons sukses mengembalikan seluruh atribut operasi beserta ID berformat
`OPR-...` yang dihasilkan aplikasi.

Operasi yang tersimpan dapat dibaca melalui
`GET /api/v1/daily-operations/{operation_id}`.

## Impor data historis

Unggah CSV UTF-8 atau Excel `.xlsx` melalui form
`http://127.0.0.1:8000/impor-data-historis` atau `POST /api/v1/historical-datasets`
dengan field multipart `file`. Setiap unggahan membuat versi dataset baru; data yang sudah
diperbaiki dapat diunggah ulang tanpa menimpa versi sebelumnya.

Kolom wajib adalah kategori ANGBER, mode aktivitas, jarak total, bahan bakar disiapkan, dan
sumber jarak. Header jam lifting menerima `Jam Lifting`, `Jam Operasi Lifting`, atau
`Lifting Hours`. Respons impor memuat operasi valid, laporan koreksi per sheet/baris, dan
provenans nilai mentah. Baris kalender yang tidak berisi nilai operasi diabaikan. Operasi
valid suatu versi dapat dibaca untuk pelatihan melalui
`GET /api/v1/dataset-versions/{dataset_version_id}/daily-operations`.

## Kandidat baseline dan prediksi

Latih kandidat regresi linear yang dapat ditelusuri secara manual melalui
`POST /api/v1/dataset-versions/{dataset_version_id}/baseline-candidates`. Model memakai satu
kontrak fitur `baseline-v1` untuk pelatihan dan inferensi, serta menyimpan artefak dan parameter
di MLflow lokal. Kandidat berstatus `candidate` dan tidak dapat dipakai untuk prediksi sampai
manager memilih promosi manual. Promosi dilakukan melalui
`POST /api/v1/model-candidates/{model_version_id}/promote`; model aktif sebelumnya berubah menjadi
`retired`, sehingga riwayat pelayanannya tetap dapat diaudit. Endpoint tersebut aman diulang untuk
model yang sudah aktif, tetapi model pensiun tidak dapat dipromosikan kembali.

Bandingkan kandidat dengan model aktif pada operasi yang memiliki bahan bakar aktual melalui
`GET /api/v1/model-candidates/{model_version_id}/comparison`. Respons menyajikan MAE, RMSE,
sMAPE, dan cakupan interval untuk keseluruhan serta per kategori ANGBER. Halaman
`/pengelolaan-model` dan `GET /api/v1/model-governance-dashboard` memperlihatkan kandidat,
rekomendasi pelatihan ulang berbasis MAE aktif, dan tindakan promosi manual; dashboard tidak
memiliki jalur deploy otomatis. Ambang MAE dapat diatur dengan
`FUEL_PREDICTOR_MAX_ACTIVE_MODEL_MAE_LITERS` (default `5`).

Setelah sebuah kandidat dipromosikan, planner dapat memakai tombol **Buat estimasi kebutuhan BBM** pada form,
atau memanggil `POST /api/v1/daily-operations/{operation_id}/predictions`. Respons memuat
estimasi kebutuhan dari riwayat bahan bakar disiapkan, alokasi rekomendasi, interval
ketidakpastian, sumber jarak, dan lineage input/fitur/dataset/model. Itu bukan klaim konsumsi
aktual. Alokasi menerapkan kebijakan awal yang dapat diatur melalui
`FUEL_PREDICTOR_INITIAL_SAFETY_MARGIN_LITERS` (default `5`); kebijakan tersebut secara eksplisit
bukan jaminan 99% sebelum ada kalibrasi bahan bakar aktual.

Direktori MLflow lokal dapat diatur melalui `FUEL_PREDICTOR_MLFLOW_TRACKING_DIRECTORY` (default
`.fuel_predictor/mlruns`).

Secara opsional set `FUEL_PREDICTOR_GOOGLE_MAPS_API_KEY` untuk memakai Google Maps Routes API
sebagai adapter rute. Tanpa kunci atau saat penyedia gagal, planner tetap dapat menyimpan operasi
dengan jarak manual dan hasil prediksi menandai fallback tersebut secara eksplisit.

## Prediksi operasi massal

Planner dapat membuka `http://127.0.0.1:8000/prediksi-operasi-massal` untuk mengunduh template
dan mengunggah rencana operasi CSV UTF-8 atau Excel `.xlsx`. Template juga tersedia melalui:

- `GET /api/v1/bulk-operation-predictions/template?format=xlsx`
- `GET /api/v1/bulk-operation-predictions/template?format=csv`

Kirim berkas ke `POST /api/v1/bulk-operation-predictions` dengan field multipart `file`. Kolom
wajib adalah **Kategori ANGBER**, **Mode Aktivitas**, **Jarak Total (km)**, dan **Sumber Jarak**.
**Jam Lifting** dan **Urutan Pemberhentian** opsional; tulis urutan berhenti planner dengan `>`
misalnya `Depo > Site A > Depo`.

Setiap baris valid menjalankan use case yang sama dengan API operasi tunggal: sistem menghitung
rute sesuai urutan yang diberikan (atau memakai jarak manual saat penyedia rute tidak tersedia),
membuat ID operasi `OPR-...`, lalu membuat dan menyimpan prediksi. Respons menyertakan raw source
provenance, operation ID, dan lineage model/dataset/fitur untuk setiap baris yang diterima; sumber
baris valid juga dicatat dalam database. Baris tidak valid dikarantina dengan alasan koreksi
berbahasa Indonesia tanpa menghalangi baris valid. Hasil selalu membedakan **estimasi kebutuhan
BBM** dari **alokasi rekomendasi** yang konservatif.

## Bahan bakar aktual dan evaluasi

Catat satu hasil operasi melalui form `http://127.0.0.1:8000/bahan-bakar-aktual` atau `POST
/api/v1/daily-operations/{operation_id}/actual-fuel` dengan `actual_fuel_liters` dan
`measurement_source` (`manual_entry`, `fuel_meter`, atau `receipt`). Satu catatan aktual disimpan
untuk setiap operasi agar input ulang tidak diam-diam mengganti ground truth; prepared fuel dan
prediksi tetap tidak berubah.

Untuk impor, gunakan form `http://127.0.0.1:8000/bahan-bakar-aktual-massal`, template berikut,
atau `POST /api/v1/bulk-actual-fuel` dengan field multipart `file`:

- `GET /api/v1/bulk-actual-fuel/template?format=xlsx`
- `GET /api/v1/bulk-actual-fuel/template?format=csv`

Kolom wajib adalah **ID Operasi** dan **Bahan Bakar Aktual (L)**. **Sumber Pengukuran** opsional;
jika kosong, nilainya dicatat sebagai `spreadsheet_import`. Baris valid tetap disimpan sedangkan
ID operasi yang tidak ditemukan, nilai tidak valid, dan catatan duplikat dilaporkan dalam laporan
koreksi dengan provenance sheet/baris.

`GET /api/v1/prediction-performance` dan halaman `/kinerja-prediksi` menunjukkan metrik dari
catatan aktual yang memiliki prediksi: MAE, RMSE, sMAPE, dan persentase cakupan interval. Metrik
ditampilkan untuk keseluruhan serta setiap kategori ANGBER; ketika belum ada kecocokan, nilai
metrik ditampilkan sebagai belum cukup data.

## Pemantauan operasi dan alert lokal

`GET /api/v1/monitoring-dashboard` dan halaman `/pemantauan-operasi` merekonsiliasi alert lokal
secara idempoten: alert memiliki kunci stabil, waktu pertama/terakhir teramati, dan waktu selesai
saat kondisinya pulih. Dashboard menampilkan ringkasan setiap validasi dataset dan baris
karantina yang belum diperbaiki, prediksi tanpa Actual Fuel setelah batas waktu, drift fitur
antara dataset model aktif dan input prediksi, serta MAE bergulir dan degradasi per kategori.

Evidently menjalankan pemeriksaan drift sepenuhnya di proses aplikasi; tidak ada data atau hasil
yang dikirim ke layanan pihak ketiga. Pemeriksaan drift mulai ditampilkan saat masing-masing
dataset referensi dan input prediksi memiliki sedikitnya 20 baris; sebelumnya statusnya **belum
cukup data**. Batas lokal dapat diatur melalui variabel berikut:

- `FUEL_PREDICTOR_MISSING_ACTUAL_AFTER_DAYS` (default `7`)
- `FUEL_PREDICTOR_MONITORING_DRIFT_SHARE_THRESHOLD` (default `0.5`)
- `FUEL_PREDICTOR_MONITORING_ROLLING_ERROR_WINDOW` (default `7` catatan aktual)
- `FUEL_PREDICTOR_MONITORING_MIN_MATCHED_OUTCOMES` (default `3`)
- `FUEL_PREDICTOR_MAX_ACTIVE_MODEL_MAE_LITERS` (default `5`, dipakai juga sebagai ambang degradasi)

Monitoring hanya memberi signal untuk tindak lanjut. Latih, bandingkan, dan promosikan kandidat
tetap tindakan manual di halaman pengelolaan model.

## Pemeriksaan pengembangan

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy src tests
.\.venv\Scripts\python.exe -m ruff check src tests
```
