# Panduan Operator — Perencana Operasi Harian

Panduan ini untuk orang yang memakai aplikasi setiap hari. Tidak ada perintah teknis di sini.
Kalau ada langkah yang meminta Anda mengetik perintah, itu ada di
[runbook pemulihan](recovery-runbook.md) dan bukan tugas Anda.

> **Satu hal yang harus dipahami sebelum mulai.**
> Angka yang diberikan aplikasi ini adalah **perkiraan bahan bakar yang perlu disiapkan**,
> bukan catatan bahan bakar yang benar-benar terpakai. Angka itu membantu Anda menyiapkan,
> bukan menggantikan pencatatan aktual. Setiap prediksi selalu menampilkan kalimat ini juga.

---

## Daftar isi

1. [Masuk ke aplikasi](#1-masuk-ke-aplikasi)
2. [Membuat satu prediksi](#2-membuat-satu-prediksi)
3. [Membuat banyak prediksi sekaligus](#3-membuat-banyak-prediksi-sekaligus)
4. [Mencatat bahan bakar aktual](#4-mencatat-bahan-bakar-aktual)
5. [Membaca halaman Pemantauan](#5-membaca-halaman-pemantauan)
6. [Mengganti model](#6-mengganti-model)
7. [Mengelola kredensial agen](#7-mengelola-kredensial-agen)
8. [Kalau ada yang tidak beres](#8-kalau-ada-yang-tidak-beres)

---

## 1. Masuk ke aplikasi

1. Buka alamat aplikasi di peramban (Chrome, Edge, atau Firefox).
2. Isi nama pengguna dan kata sandi, lalu tekan **Masuk**.

Menu di sebelah kiri hanya menampilkan halaman yang boleh Anda buka. Kalau Anda tidak melihat
suatu menu, berarti peran akun Anda memang tidak mencakupnya — itu bukan kerusakan.

**Kalau kata sandi ditolak:** periksa huruf besar/kecil. Setelah beberapa kali gagal, sistem
menahan percobaan berikutnya sebentar. Tunggu, lalu coba lagi.

**Lupa kata sandi:** minta administrator mengatur ulang — di menu **Pengguna**, tombol
**Atur ulang kata sandi** pada baris akun Anda. **Mengganti kata sandi sendiri:** tautan
**Ubah kata sandi** di bawah nama Anda pada menu samping; Anda diminta kata sandi yang lama
dulu, lalu masuk lagi dengan yang baru.

![Halaman Masuk: kartu berisi kolom nama pengguna, kata sandi, dan tombol Masuk.](images/01-masuk.png)

---

## 2. Membuat satu prediksi

1. Menu **Buat Prediksi**.
2. Isi:
   - **Kendaraan** — pilih unit dari daftar, misalnya `VT 01` atau `Truck Crane 01`. Hanya ini
     yang perlu Anda sebutkan; tipe dan grupnya (misalnya *Vacuum Truck*) dibaca aplikasi dari
     katalog armada dan ditampilkan di hasil sebagai keterangan.
   - **Rute & pemberhentian** — ketik nama lokasi; daftar menyaring sambil Anda mengetik.
     Nama yang tidak ada di katalog ditolak beserta usulan nama yang mirip.
   - **Mode aktivitas** — `transport`, `lifting`, atau `transport_and_lifting`.
   - **Jam lifting** — wajib diisi kalau mode mencakup lifting.
   - **Jarak tempuh** — dihitung otomatis dari rute, jadi biasanya tidak ada yang perlu diisi.
     Bila penyedia rute gagal menghitung, penyimpanan ditolak dan kolom **Jarak tempuh manual**
     muncul untuk diisi sendiri (seluruh perjalanan, termasuk kembali); estimasinya lalu
     ditandai memakai jarak manual. Pada instalasi tanpa penyedia rute, kolom ini selalu ada
     dan wajib diisi.
3. Tekan **Simpan & buat estimasi**. Operasi tersimpan lebih dulu, jadi angkanya bisa
   ditelusuri kembali nanti, lalu estimasinya langsung ditampilkan.

Hasilnya menampilkan:

| Yang ditampilkan | Artinya |
|---|---|
| Perkiraan kebutuhan | Estimasi bahan bakar untuk operasi ini. |
| Rekomendasi alokasi | Perkiraan ditambah margin aman. **Angka inilah yang dipakai menyiapkan.** |
| Rentang ketidakpastian | Batas bawah dan atas yang masuk akal. Rentang lebar = model kurang yakin. |
| Model yang dipakai | Versi model yang menghitung. Berguna saat menelusuri angka lama. |

![Hasil estimasi: tiga kotak angka — alokasi rekomendasi, estimasi kebutuhan BBM, rentang ketidakpastian — lalu ID operasi dengan tombol Salin ID, kendaraan, aktivitas, rute, jarak total, dan tombol Catat BBM aktual untuk operasi ini.](images/02-hasil-prediksi.png)

Perhatikan kotak hijau di atas: nilai ini **estimasi bahan bakar disiapkan**, bukan konsumsi aktual yang telah diverifikasi. Kalimat itu selalu ikut ditampilkan.

Estimasi yang sudah dibuat bisa dibuka lagi kapan saja dari menu **Riwayat Prediksi**:
daftarnya terbaru di atas, ada kotak pencarian, dan tiap baris menunjukkan apakah BBM aktualnya
sudah dicatat.

**Kalau muncul "Belum ada kandidat baseline terlatih":** belum ada model yang aktif.
Hubungi penanggung jawab model — lihat [bagian 6](#6-mengganti-model).

---

## 3. Membuat banyak prediksi sekaligus

1. Menu **Prediksi Massal**.
2. Unduh templat yang disediakan di halaman itu. **Selalu pakai templat itu**, jangan membuat
   kolom sendiri — urutan dan nama kolom harus persis.
3. Isi satu baris per operasi.
4. Unggah berkasnya.

Aplikasi memproses baris yang benar dan **menahan** baris yang bermasalah. Baris bermasalah
ditampilkan beserta alasannya, misalnya `Jam lifting harus lebih besar dari 0 untuk mode yang
mencakup lifting`.

Perbaiki baris tersebut di berkas asli, lalu unggah ulang. Baris yang sudah berhasil tidak
terhitung dua kali.

![Hasil unggah massal: 4 baris berhasil diprediksi dengan tombol Unduh hasil (CSV), dan laporan koreksi berisi 3 baris dikarantina dengan alasan masing-masing — jam lifting kosong, jarak bukan angka, dan jarak bernilai negatif.](images/03-unggah-massal.png)

Kolom **Alasan** pada Laporan koreksi menyebutkan persis apa yang salah pada tiap baris, sehingga Anda tahu apa yang perlu diperbaiki di berkas sumber.

---

## 4. Mencatat bahan bakar aktual

Ini bagian yang paling sering terlewat, dan yang paling menentukan.

**Tanpa angka aktual, aplikasi tidak bisa mengukur seberapa tepat prediksinya.** Model bisa
memburuk berbulan-bulan tanpa ada yang tahu.

- **Satu per satu:** menu **Catat Aktual**. Daftar *Menunggu BBM aktual* di halaman itu
  memuat operasi yang belum dilaporkan, terbaru di atas. Tekan **Catat** di baris operasinya —
  ID-nya terisi sendiri — lalu isi jumlah liter sebenarnya. Halaman hasil estimasi juga punya
  tombol **Catat BBM aktual untuk operasi ini** yang langsung ke formulir yang sama.
- **Sekaligus:** menu **Impor Massal**, pakai templatnya, sama seperti prediksi massal.

Lakukan ini rutin — mingguan sudah cukup.

---

## 5. Membaca halaman Pemantauan

Menu **Pemantauan**. Bagian yang perlu Anda perhatikan:

**Peringatan aktif.** Setiap peringatan menyebutkan tindakan yang perlu diambil. Ikuti
kalimat "Tindakan:" — kalimat itu memang ditulis untuk dibaca tanpa latar belakang teknis.

**Penggolongan kendaraan berubah.** Muncul bila katalog armada (tipe atau grup sebuah unit)
diubah setelah model aktif dilatih, dan model itu memang memakai penggolongan tersebut. Prediksi
tetap berjalan dengan penggolongan lama; tindakannya: latih kandidat baru dari data terbaru, lalu
aktifkan ([bagian 6](#6-mengganti-model)).

**Pergeseran fitur (drift).** Artinya pola operasi sekarang berbeda dari data yang dipakai
melatih model. **Ini belum tentu kesalahan.** Rute baru atau musim yang berbeda memang membuat
pergeseran. Yang perlu Anda tanyakan: _apakah memang ada yang berubah di lapangan?_
- Ya, dan akan berlanjut → minta model dilatih ulang.
- Tidak ada yang berubah → periksa dulu cara data dimasukkan.

Halaman ini selalu menyebutkan **berapa banyak data** yang dibandingkan. Kalau jumlahnya kecil,
kesimpulannya lemah — jangan mengambil keputusan besar dari situ.

**Kinerja model.** Dihitung dari operasi yang sudah punya angka aktual. Kalau tertulis data
belum cukup, itu jujur — bukan kerusakan. Isi lebih banyak angka aktual
([bagian 4](#4-mencatat-bahan-bakar-aktual)). Grafik *Tren kesalahan bergulir* menunjukkan
arahnya: garis yang naik melewati garis putus-putus berarti prediksi makin meleset; titik
terakhir berwarna merah bila sudah melewati batas.

**Kesehatan Sistem.** Menunjukkan kapan pemantauan terakhir berhasil dan kapan pencadangan
terakhir berhasil. Kalau tertulis **Kedaluwarsa**, angka di halaman ini mungkin sudah lama —
hubungi penanggung jawab teknis.

![Kesehatan Sistem: 4 peringatan aktif dikelompokkan menjadi Kinerja model menurun (kritis) dan Aktual belum dicatat (peringatan), masing-masing dengan kalimat Tindakan; 3 aktual BBM tertunda dengan tombol Catat aktual; pemantauan terjadwal Terkini.](images/04-kesehatan-sistem.png)

Spanduk di atas juga memberi tahu apakah peringatan dikirim ke luar aplikasi. Bila tertulis *saluran pemberitahuan belum dikonfigurasi*, peringatan hanya terlihat di halaman ini — sampaikan ke penanggung jawab teknis.

---

## 6. Mengganti model

Hanya untuk akun dengan peran pengelola model.

**Model pertama, atau melatih ulang dari riwayat:** menu **Impor Data Historis**, unggah
riwayat operasi beserta BBM yang disiapkan (templatnya ada di halaman itu). Setelah impor,
tekan **Latih kandidat baseline secara manual**; kandidatnya lalu muncul di **Pengelolaan
Model** untuk dibandingkan dan dipromosikan. Selama belum ada model aktif, halaman
**Ringkasan** menampilkan ketiga langkah ini.

**Mengunggah paket model baru:** menu **Unggah Kandidat**, pilih berkas `.zip` dari pembuat model.

Aplikasi memeriksa paket itu lebih dulu. Kalau ada yang tidak beres, paket **ditolak** dan
alasannya ditampilkan. Model yang sedang berjalan **tidak tersentuh** — mengunggah tidak pernah
mengganti model secara diam-diam.

**Mengaktifkan:** menu **Pengelolaan Model**, tekan **Bandingkan** pada kandidatnya. Halaman
perbandingan langsung menyebut kesimpulannya di kotak paling atas — *Kandidat lebih tepat*,
*Kandidat kurang tepat*, atau *Belum bisa dibandingkan* kalau belum ada BBM aktual untuk
mengujinya — lalu angka keduanya berdampingan. Kalau setuju, tekan **Promosikan kandidat ini**
dan konfirmasi.

Kalau aktivasi gagal, model lama **tetap melayani prediksi**. Anda akan melihat pesan yang
menjelaskan sebabnya. Tidak ada yang perlu Anda pulihkan sendiri.

Kalau setelah aktivasi muncul pesan bahwa **pemeriksaan gagal**, model baru sudah terlanjur
melayani. Segera kembalikan: di **Pengelolaan Model**, tabel *Semua versi*, tekan
**Aktifkan kembali** pada versi sebelumnya (tersedia untuk versi yang paketnya masih
tersimpan), lalu hubungi penanggung jawab teknis.

![Pengelolaan Model: model aktif beserta MAE-nya, satu kandidat menunggu keputusan dengan tombol Bandingkan dan Promosikan, dan tabel Semua versi yang menampilkan status tiap versi.](images/05-pengelolaan-model.png)

Tombol **Promosikan** — selalu dengan konfirmasi — adalah satu-satunya cara model berganti.
Tidak ada promosi otomatis.

---

## 7. Mengelola kredensial agen

Hanya untuk akun administrator. Menu **Integrasi Agen**.

Ini untuk memberi akses kepada asisten AI atau sistem lain yang perlu membaca prediksi dan
pemantauan.

**Menerbitkan:** isi nama klien, centang cakupan yang diperlukan, tekan **Terbitkan**.

> **Kredensial hanya ditampilkan satu kali.** Salin saat itu juga. Sistem hanya menyimpan
> sidik digitalnya, jadi kredensial yang hilang **harus diterbitkan ulang** — tidak bisa
> dilihat kembali. Ini disengaja.

**Mencabut:** tekan **Cabut** pada baris klien tersebut. Berlaku seketika.

Berikan cakupan seperlunya saja. Satu klien yang dicabut tidak mengganggu klien lain.

**Menyerahkan ke pihak lain:** begitu kredensial terbit, di bawahnya muncul bagian
**Cara menghubungkan** berisi alamat MCP aplikasi ini dan potongan konfigurasi yang sudah
terisi kredensial untuk agen pengkodean yang umum dipakai (Claude Code, Cursor, Codex, VS Code).
Salin potongan yang sesuai dan kirimkan ke pengembang di pihak lain lewat jalur yang aman —
potongan itu memuat kredensialnya. Mereka tidak memerlukan akun di aplikasi ini; cukup
kredensial itu. Bila mereka butuh penjelasan alat-alatnya, berikan berkas
`docs/production/mcp-integration.md`.

### 7a. Menyambungkan agen Anda sendiri

Semua akun. Menu **Agen Saya**.

Untuk agen pengkodean di laptop Anda sendiri (Claude Code, Cursor, dan sejenisnya) tidak perlu
kredensial dari administrator. Tambahkan alamat MCP yang tertera di halaman itu ke agen Anda
*tanpa* kredensial; agen akan membuka peramban ke halaman izin aplikasi ini. Periksa nama agen
dan alamat kembalinya, centang yang boleh dilakukannya, lalu tekan **Izinkan**.

Agen itu bertindak atas nama akun Anda dan tidak pernah bisa melakukan lebih dari yang boleh
Anda lakukan. Di **Agen Saya** Anda melihat setiap agen yang tersambung dan dapat menekan
**Cabut** kapan saja; berlaku seketika. Sambungan yang tidak dipakai 30 hari berakhir sendiri.

Administrator melihat sambungan semua pengguna di bagian bawah **Integrasi Agen** dan dapat
mencabutnya juga.

---

## 8. Kalau ada yang tidak beres

| Yang Anda lihat | Yang perlu dilakukan |
|---|---|
| Halaman tidak terbuka sama sekali | Hubungi penanggung jawab teknis. Sebutkan jam kejadiannya. |
| "Sesi formulir sudah tidak berlaku" | Muat ulang halaman, isi lagi, kirim ulang. Halaman terbuka terlalu lama. |
| "Belum ada kandidat baseline terlatih" | Belum ada model aktif. Lihat [bagian 6](#6-mengganti-model). |
| Baris tertahan saat unggah | Perbaiki baris itu di berkas asli, unggah ulang. |
| Kesehatan Sistem "Kedaluwarsa" | Pemantauan berhenti berjalan. Hubungi penanggung jawab teknis. |
| Prediksi terasa jauh dari kenyataan | Catat aktualnya dulu, lalu lihat Pemantauan. Kalau MAE naik, minta model dilatih ulang. |

**Saat melapor, sebutkan tiga hal ini** — dengan ini masalah biasanya ketemu jauh lebih cepat:

1. Halaman apa yang sedang Anda buka.
2. Apa yang Anda tekan atau isi.
3. Pesan yang muncul, disalin apa adanya (atau tangkapan layarnya).

---

## Yang tidak perlu Anda khawatirkan

- **Prediksi tidak pernah mengubah data historis.** Menekan Hitung berkali-kali aman.
- **Mengunggah model tidak pernah langsung menggantikan model aktif.**
- **Aktivasi yang gagal tidak pernah membuat aplikasi kehilangan model.**
- **Peringatan pemantauan bukan berarti aplikasi rusak.** Sebagian besar berarti ada data yang
  perlu dilengkapi.
