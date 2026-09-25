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
7. [Mengelola pengguna](#6b-mengelola-pengguna)
8. [Mengelola kredensial agen](#7-mengelola-kredensial-agen)
8. [Kalau ada yang tidak beres](#8-kalau-ada-yang-tidak-beres)

---

## 1. Masuk ke aplikasi

1. Buka alamat aplikasi di peramban (Chrome, Edge, atau Firefox).
2. Isi nama pengguna **atau email** akun Anda dan kata sandi, lalu tekan **Masuk**.

Setiap halaman daftar — riwayat prediksi, pengguna, catatan audit, versi model — punya
kotak **Cari**, jumlah baris **Per halaman** (5 baris bila tidak diubah), dan tombol halaman
di bawahnya. Untuk mengurutkan, tekan **judul kolom** yang bertanda panah: tekan sekali
untuk mengurutkan menurut kolom itu, tekan lagi untuk membalik arahnya. Di layar sempit,
judul-judul itu tampil sebagai pilihan **Urutkan** di atas daftar. Alamat halaman ikut
berubah, jadi tampilan yang sama bisa dibuka lagi dari riwayat peramban atau dibagikan.

Menu di sebelah kiri hanya menampilkan halaman yang boleh Anda buka. Ada dua peran:

- **Operator** — membuat prediksi (satu per satu atau dari berkas), melihat riwayatnya, dan
  mencatat BBM aktual. Bagian 2–4 panduan ini.
- **Administrator** — semuanya: ditambah pemantauan, model, pengguna, dan integrasi agen.
  Bagian 5–7 hanya berlaku untuk administrator.

Kalau Anda tidak melihat suatu menu, berarti peran akun Anda memang tidak mencakupnya — itu
bukan kerusakan.

**Kalau kata sandi ditolak:** periksa huruf besar/kecil. Setelah beberapa kali gagal, sistem
menahan percobaan berikutnya sebentar. Tunggu, lalu coba lagi.

**Lupa kata sandi:** tekan **Lupa kata sandi?** di halaman masuk, isi nama pengguna atau email,
lalu buka tautan yang dikirim ke email akun Anda (berlaku 30 menit, sekali pakai) dan pilih kata
sandi baru. Bila akun Anda belum punya email, atau halaman itu menyebut pengiriman email belum
diaktifkan, minta administrator mengatur ulang — di menu **Pengguna**, tombol
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
   - **Aktivitas** — *Mobilisasi*, atau *Mobilisasi + lifting*. Pilihan kedua hanya bisa dipilih
     untuk kendaraan yang bisa lifting (Truck Crane 01, Truck Crane 02, Wheel Crane — kolom
     *Lifting* di menu **Armada**); untuk kendaraan lain pilihan itu tidak aktif.
   - **Jam lifting** — wajib diisi kalau aktivitas mencakup lifting.
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

![Hasil estimasi: tiga kotak angka — alokasi rekomendasi, estimasi kebutuhan BBM, rentang ketidakpastian — lalu kode operasi dengan tombol Salin kode, kendaraan, aktivitas, rute, jarak total, dan tombol Catat BBM aktual untuk operasi ini.](images/02-hasil-prediksi.png)

Perhatikan kotak hijau di atas: nilai ini **estimasi bahan bakar disiapkan**, bukan konsumsi aktual yang telah diverifikasi. Kalimat itu selalu ikut ditampilkan.

**Catat kode operasinya.** Setiap operasi mendapat kode, misalnya `260924-0914-VT-P410-VT01`:

| Bagian | Artinya |
|---|---|
| `260924-0914` | Tanggal dan jam operasi dibuat (24 September 2026, 09:14, waktu setempat) |
| `VT` | Grup kendaraan: Vacuum Truck |
| `P410` | Tipe kendaraan: Scania P410 6X6 |
| `VT01` | Unitnya: VT 01 |

Di bawah kode, halaman estimasi menuliskan arti tiap bagian untuk kendaraan itu. Tulis kode ini
di nota atau catatan BBM. Saat BBM aktualnya dilaporkan nanti, kode inilah yang diketik — huruf
besar atau kecil tidak berpengaruh.

Kalau kendaraan yang sama dibuatkan operasi dua kali dalam menit yang sama — misalnya tombol
tertekan dua kali — operasi kedua mendapat akhiran `-2` (`260924-0914-VT-P410-VT01-2`). Batalkan operasi yang
tidak terpakai: tombol **Batalkan operasi** di halaman estimasinya meminta alasan singkat, lalu
operasi itu keluar dari daftar menunggu BBM aktual. Datanya tetap tersimpan dan terlihat di
**Riwayat Prediksi** dengan tanda *Dibatalkan*. Operasi yang BBM aktualnya sudah dicatat tidak
bisa dibatalkan.

Daftar lengkap kode kendaraan — grup, tipe, dan ejaan lain tiap unit — ada di menu **Armada**.
Buka menu itu kalau ragu kode mana milik kendaraan mana.

**Cetak slipnya.** Tombol **Cetak slip** di halaman estimasi membuka slip BBM siap cetak: kode
operasi besar-besar, kendaraan, rute, alokasi, dan baris kosong untuk liter yang benar-benar
terpakai, cara mengukurnya, dan siapa yang mencatat. Bawa slip itu ke titik pengisian BBM; setelah
operasi selesai, liter di slip itulah yang dicatat.

Aktivitas hanya dua: **Mobilisasi**, atau **Mobilisasi + lifting**. Pilihan kedua hanya aktif
untuk kendaraan yang bisa lifting (kolom *Lifting* di menu **Armada**).

Estimasi yang sudah dibuat bisa dibuka lagi kapan saja dari menu **Riwayat Prediksi**:
daftarnya terbaru di atas, ada kotak pencarian, dan tiap baris menunjukkan apakah BBM aktualnya
sudah dicatat. Ketik *menunggu* di kotak pencarian untuk melihat operasi yang BBM aktualnya belum
dicatat, atau *dibatalkan* untuk operasi yang dibatalkan.

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

Setiap baris yang berhasil mendapat kode operasinya sendiri. Unduh hasilnya (CSV): kolom
**Kode operasi** ada di sebelah baris sumbernya, jadi kode tiap operasi bisa langsung dicatat.
Tombol **Cetak semua slip** mencetak slip BBM untuk setiap operasi dalam unggahan itu, satu slip
per halaman.

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
  memuat operasi yang belum dilaporkan, terbaru di atas, masing-masing dengan kode operasinya.
  Ketik kode yang Anda catat, atau tekan **Catat** di baris operasinya — kodenya terisi sendiri —
  lalu isi jumlah liter sebenarnya. Begitu kodenya cocok, formulir menampilkan operasinya
  (kendaraan, waktu prediksi, alokasi) supaya Anda yakin mencatat operasi yang benar. Kalau liter
  yang diketik jauh dari alokasinya, muncul peringatan: periksa lagi angka dan kodenya.
- **Sekaligus, cara termudah:** di kotak **Isi sekaligus lewat Excel** — ada di halaman Catat
  Aktual, Ringkasan, dan Kesehatan Sistem — tekan **Unduh daftarnya** (atau **Unduh operasi yang
  menunggu** di Impor Massal). Berkasnya sudah berisi kode, kendaraan, waktu,
  rute, dan alokasi setiap operasi yang menunggu; isi saja kolom **Bahan Bakar Aktual (L)**, lalu
  unggah di menu **Impor Massal**. Baris yang belum diisi dilewati, jadi berkas yang sama boleh
  diisi bertahap sepanjang minggu dan diunggah berkali-kali.
- **Dengan templat kosong:** menu **Impor Massal**, isi kolom **Kode Operasi** dengan kode yang
  dicatat; ID lama `OPR-…` juga masih diterima.

Lakukan ini rutin — mingguan sudah cukup.

---

## 5. Membaca halaman Pemantauan

Hanya untuk akun administrator. Menu **Pemantauan**. Bagian yang perlu Anda perhatikan:

**Kesehatan Sistem** adalah daftar tugas. Kotak paling atas menjawab satu pertanyaan: *ada yang
perlu ditangani?* Di bawahnya, setiap hal yang perlu ditangani punya kartunya sendiri: apa yang
ditemukan, seberapa mendesak (**Kritis** = hari ini), dan tombol untuk menanganinya. Operasi yang
belum dicatat BBM aktualnya, misalnya, langsung bisa diunduh sebagai Excel, diisi, lalu diimpor
kembali. Alasan dan langkah lengkapnya ada di lipatan *Kenapa ini penting, dan langkah
lengkapnya*. Yang sudah baik dirangkum di **Selebihnya**.

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

![Kesehatan Sistem: 3 hal perlu ditangani. Kinerja model menurun (kritis) dengan tombol Bandingkan dan ganti model; 1 baris impor perlu diperbaiki dengan tombol Impor ulang data historis; 3 operasi belum dicatat BBM aktualnya dengan langkah Isi sekaligus lewat Excel; lalu Selebihnya dan Perawatan server.](images/04-kesehatan-sistem.png)

**Perawatan server** di bagian bawah untuk penanggung jawab teknis: kapan pemeriksaan terjadwal
dan pencadangan terakhir berjalan, dan apakah peringatan dikirim ke luar aplikasi. Kalau tertulis
**Terlambat**, **Belum pernah berjalan**, atau *saluran pemberitahuan belum dikonfigurasi*,
sampaikan ke penanggung jawab teknis.

---

## 6. Mengganti model

Hanya untuk akun administrator.

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

## 6b. Mengelola pengguna

Hanya untuk akun administrator. Menu **Pengguna**.

Halaman ini adalah daftar semua akun: berapa yang aktif, kapan tiap orang terakhir masuk,
dan berapa prediksi serta BBM aktual yang mereka buat dalam 30 hari terakhir. Cari
berdasarkan nama, nama pengguna, atau email; **Status** menyaring akun aktif atau nonaktif.

- **Tambah pengguna** — nama pengguna, nama, email (opsional), kata sandi awal, dan peran.
  Sampaikan kata sandi awal secara aman; pengguna bisa menggantinya sendiri lewat
  **Ubah kata sandi**.
- **Buka** pada satu baris membawa Anda ke halaman orang itu: ubah nama, email, atau peran
  (peran Anda sendiri hanya bisa diubah administrator lain), **Atur ulang kata sandi**,
  **Nonaktifkan** atau **Aktifkan kembali**, daftar operasi terakhir yang dibuatnya, dan
  jejak aktivitasnya dari catatan audit.

Akun yang dinonaktifkan langsung keluar dan tidak bisa masuk lagi; pekerjaan dan catatannya
tetap tersimpan, dan akun bisa diaktifkan kembali kapan saja.

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

Hanya untuk akun administrator. Menu **Agen Saya**. Agen yang tersambung bertindak dengan hak
akses akun Anda; operator tidak dapat menyambungkan agen.

Untuk agen pengkodean di laptop Anda sendiri (Claude Code, Cursor, dan sejenisnya) tidak perlu
kredensial dari administrator. Tambahkan alamat MCP yang tertera di halaman itu ke agen Anda
*tanpa* kredensial; agen akan membuka peramban ke halaman izin aplikasi ini. Periksa nama agen
dan alamat kembalinya, centang yang boleh dilakukannya, lalu tekan **Izinkan**.

Agen itu bertindak atas nama akun Anda dan tidak pernah bisa melakukan lebih dari yang boleh
Anda lakukan. Di **Agen Saya** Anda melihat setiap agen yang tersambung, dengan tiga tombol:

- **Beri nama** — nama Anda sendiri untuk sambungan itu, misalnya "Laptop kantor", supaya dua
  sambungan dari program yang sama bisa dibedakan. Hanya tampilan; agen tidak terpengaruh.
- **Cabut** — berlaku seketika; agen langsung kehilangan akses. Sambungan yang tidak dipakai
  30 hari berakhir sendiri.
- **Hapus** — muncul setelah sambungan dicabut atau berakhir, untuk mengeluarkannya dari
  daftar. Catatan auditnya tetap ada.

Administrator melihat sambungan semua pengguna di bagian bawah **Integrasi Agen** dengan
tombol yang sama.

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
