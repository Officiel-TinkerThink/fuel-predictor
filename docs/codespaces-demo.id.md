# Menjalankan demo di GitHub Codespaces

*[English version](codespaces-demo.md)*

Panduan langkah demi langkah untuk meninjau aplikasi perencana BBM tanpa
memasang apa pun. Codespace adalah komputer sementara yang dijalankan GitHub di
dalam browser; semua langkah di bawah terjadi di dalamnya dan hilang ketika
Codespace itu Anda hapus.

Sekitar 10 menit, sebagian besar hanya menunggu proses build pertama.

---

## Yang akan Anda dapatkan

Empat container, dijalankan oleh satu perintah:

| Layanan | Fungsinya |
|---|---|
| `app` | Aplikasi perencananya sendiri, pada port 8000 |
| `db` | PostgreSQL, menyimpan operasi, prediksi, dan katalog |
| `mlflow` | Penyimpan model, pada port 5000 |
| `seed` | Berjalan sekali untuk mengisi basis data kosong, lalu berhenti |

Basis datanya sudah terisi sejak awal: katalog lokasi, armada kendaraan, contoh
riwayat perjalanan, dan satu model terlatih yang sudah dipromosikan menjadi
aktif. Anda dapat langsung membuat prediksi begitu halaman terbuka.

---

## Langkah 1 — Buka Codespace

Di halaman repositori: **Code ▾ → Codespaces → Create codespace on main**.

Branch bawaan sudah memuat semuanya, jadi tidak ada yang perlu dipilih. (Bila
Anda diminta meninjau pekerjaan yang belum selesai, gunakan **New with
options…** lalu isi branch yang diberikan kepada Anda.)

## Langkah 2 — Tunggu proses penyiapan selesai

Codespace membuka satu terminal dan menjalankan penyiapannya sendiri lebih
dulu: menulis berkas `.env` berisi kata sandi basis data yang dibuat acak, lalu
membangun image container. Build ini memakan waktu sekitar lima menit pada kali
pertama dan tidak diulang.

Penyiapan selesai ketika terminal menampilkan:

```
Ready. Start the stack with:

    docker compose up
```

## Langkah 3 — Jalankan seluruh layanan

Pada terminal Codespace:

```bash
docker compose up
```

Biarkan perintah ini tetap berjalan — inilah log aplikasinya. Start pertama
menerapkan migrasi basis data lalu mengisinya, jadi beri waktu satu menit.
Baris yang Anda tunggu:

```
seed-1  |   1110 lokasi dan 23 kendaraan dimuat.
seed-1  |   Riwayat DSV-000001 diimpor: 9 baris valid.
seed-1  |   Kandidat MDL-… dilatih.
seed-1  |   Model MDL-… dipromosikan menjadi aktif.
seed-1  |   Model dibaca ulang dan menghasilkan 16.6 L untuk satu baris contoh.
seed-1  | Basis data siap dipakai: buka /prediksi dan buat satu operasi harian.
```

Baris kedua dari bawah yang paling penting: proses pengisian membaca ulang
model yang baru saja dilatih dan memakainya untuk menghitung satu baris. Jadi
"sudah terisi" berarti sebuah prediksi benar-benar sudah dihasilkan, bukan
sekadar ada berkas yang tertulis.

Setelah itu container `seed` berhenti. Itu memang seharusnya: tugasnya hanya
satu.

## Langkah 4 — Buka aplikasinya

Akan muncul notifikasi yang menawarkan membuka port 8000 di browser. Bila
terlewat, gunakan tab **Ports** di bagian bawah jendela Codespace, lalu klik
ikon bola dunia di sebelah port 8000.

Masuk dengan:

- **Nama pengguna:** `admin`
- **Kata sandi:** `angber-demo-2026`

Ini kredensial demo untuk mesin sekali pakai, ditulis ke berkas `.env` milik
Codespace itu sendiri. Kredensial ini tidak ada di dalam repositori dan tidak
dipakai di tempat lain.

## Langkah 5 — Buat satu prediksi

Buka **Buat Prediksi** pada menu samping, lalu isi satu operasi:

1. **Kendaraan** — pilih `Prime Mover — Truck`. Daftarnya adalah armada
   sebenarnya: 23 unit dalam kelompok Crane, Truck, Forklift, dan Vacuum Truck.
2. **Aktivitas** — pilih `Angkut dan lifting`. Kolom **Jam lifting** akan
   muncul; isi `3.5`.
3. **Rute & pemberhentian** — pilih `POOL LIMAU` sebagai titik keberangkatan
   dan `KM-001` sebagai pemberhentian. Peta di atasnya menggambar rute di
   antara keduanya. Gunakan **+ Tambah pemberhentian** untuk menambah
   pemberhentian, dan seret pegangan ⠿ untuk mengubah urutannya.
4. **Sumber jarak** — pilih `Input manual` lalu isi `64` km. (Alasan jarak
   otomatis belum tersedia pada demo ini ada di bagian *Batasan* di bawah.)
5. Tekan **Simpan operasi harian**, lalu **Buat estimasi kebutuhan BBM**.

Hasilnya kira-kira **51 L estimasi** dengan **56 L alokasi rekomendasi** —
rekomendasi menambahkan margin aman 5 L.

Layak dicoba berikutnya: perjalanan yang sama tanpa jam lifting, atau dengan
setengah jaraknya, untuk melihat masukan mana yang menggerakkan angkanya dan
sebesar apa.

---

## Isi basis data sejak awal

| | Jumlah | Sumbernya |
|---|---|---|
| Lokasi | 1110 | Sheet `Data Lokasi`, lengkap dengan koordinat |
| Kendaraan | 23 | Sheet `Dim_Kendaraan`, dengan peta alias dari `Peta_Nama_Sumber` |
| Riwayat perjalanan | 9 | Contoh kecil yang ikut dipaketkan bersama aplikasi |
| Model terlatih | 1, aktif | Dilatih dari sembilan perjalanan itu saat pengisian |

---

## Batasan demo ini

Hal-hal berikut adalah sifat data contohnya, bukan kesalahan yang perlu
dilaporkan:

- **Jarak jalan belum tersedia.** Peta rutenya tergambar, tetapi angka
  kilometernya membutuhkan kunci Google Maps API yang tidak ikut disertakan.
  Pilih `Input manual` dan ketik jaraknya. Untuk mengaktifkannya, isi kunci di
  `.env` sebagai `FUEL_PREDICTOR_GOOGLE_MAPS_API_KEY=…` lalu jalankan ulang
  dengan `docker compose up -d`.
- **Pilihan kendaraan belum mengubah estimasi.** Sembilan perjalanan contoh
  tidak mencatat kendaraan mana yang menjalankannya, sehingga model tidak punya
  sinyal kendaraan untuk dipelajari. Riwayat sebenarnya yang memuat kolom
  kendaraan akan mengubah hal ini — persis itulah isi Level 1 pada
  [peta jalan data](prd/prediction-data-roadmap.md).
- **Rentang ketidakpastian selalu ±1 L.** Angka itu berasal dari sisa kesalahan
  saat pelatihan, bukan ukuran seberapa tidak biasa masukan Anda, sehingga
  tetap sempit bahkan untuk perjalanan yang jauh lebih panjang daripada apa pun
  di data contoh.
- **Sembilan perjalanan belum bisa disebut sistem terlatih.** Angka akurasi
  dari demo ini tidak berarti apa-apa. Yang ditunjukkannya adalah seluruh alur
  bekerja dari ujung ke ujung.

---

## Menghentikan, menjalankan ulang, mengulang dari awal

```bash
# Berhenti, data tetap disimpan
docker compose down

# Jalankan lagi — langkah pengisian melihat model aktif sudah ada, lalu berhenti
docker compose up

# Hapus semuanya dan isi ulang dari nol
docker compose down -v && docker compose up
```

Menghapus Codespace-nya sendiri (github.com/codespaces) menghapus seluruhnya.

---

## Bila ada yang tidak beres

**Halaman tidak terbuka.** Periksa tab Ports: port 8000 harus terdaftar. Bila
`docker compose up` masih menampilkan baris-baris start, tunggu sampai muncul
`Application startup complete`.

**Muncul galat `POSTGRES_PASSWORD` saat start.** Berkas `.env` belum ada.
Jalankan ulang `bash .devcontainer/setup.sh`.

**Container `seed` melaporkan galat.** Baca dengan `docker compose logs seed`.
Untuk mencoba lagi:
`docker compose run --rm seed python -m fuel_predictor seed-demo --force`.

**Tidak bisa masuk.** Pastikan kredensial di `.env` sama dengan yang Anda
ketik; akun dibuat dari nilai-nilai itu saat aplikasi pertama kali berjalan.
Bila Anda mengubahnya setelah itu, jalankan
`docker compose down -v && docker compose up`.
