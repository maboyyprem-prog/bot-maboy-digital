# Maboyy Digital Bot

**Versi aktif:** v16.53 — flow `/tools` v16.52 dan perbaikan bug runtime, enam file flat yang sama.

## v16.53 — Perbaikan Command dan Runtime

Nama command, menu, fitur toko, dan format input lama tetap dipertahankan. Flow provider `/tools`
dari revisi v16.52 tetap tersedia: Kirim Link → Verifikasi → Apply Premium → Hasil/Riwayat.
Perubahan command lain dibatasi pada perbaikan bug serta penanganan input/session yang tidak valid.

Perbaikan:
- Menyambungkan tombol produk dan varian di Atur Harga ke handler nominal yang sudah ada.
- Session Harga Custom lama ditutup saat berpindah menu; wizard aktif tetap bisa dilanjutkan
  setelah restart. Payload session yang rusak ditangani tanpa AttributeError.
- `/owner` memeriksa akses sebelum mengubah flag upload QRIS atau membersihkan session.
- Callback produk, jumlah, keranjang, favorit, paket, dan Atur Harga menolak ID tidak valid
  serta angka di luar batas SQLite sebelum mengubah data.
- Tombol produk lama menangani produk/varian nonaktif dengan pemberitahuan yang sudah ada.
- Nama, deskripsi, dan kode produk dengan karakter HTML ditampilkan sebagai teks agar Telegram
  tidak menolak kartu produk/varian.
- Pesan callback yang tidak bisa diakses memakai fallback kirim ke chat yang sama. Pesan yang
  mengalami timeout saat dikirim tidak diulang otomatis; tombol kedaluwarsa tidak melempar error.
- Variable angka umum yang kosong/tidak valid memakai default. `ADMIN_ID` tidak terkonfigurasi
  tetap menolak akses owner. Referensi log error menyamarkan link verifikasi dan token.

Tidak ada Railway variable atau dependensi baru pada v16.53. Schema tetap **178**; tabel dan
data v16.51/v16.52 tetap dipertahankan. Konfigurasi provider mengikuti panduan v16.52 di bawah.
Paket tetap `main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.

Validasi v16.53: **68 uji regresi** dan **49 pemeriksaan runtime** lulus. Audit mencakup
285 callback, 84 handler pesan, 210 nilai tombol literal, serta 227 template tombol dinamis;
semua tombol yang diaudit menemukan handler. Seluruh 765 definisi dan 366 registrasi router
original v16.51 tetap tersedia; nama command tidak berubah. Definisi flow provider tools identik
dengan build v16.52 khusus tools. Pengujian memakai API lokal dan Telegram simulasi; apply
pada akun asli serta deployment Railway belum diuji pada sesi ini.

## v16.52 — Apply Premium dan Flow Provider Stabil

Catatan lingkup revisi v16.52 khusus tools: pengembangan hanya mencakup `/tools`; handler command
lain saat itu identik dengan v16.51. Pada v16.53, bug command lain diperbaiki tanpa mengganti fitur.

Alur `/tools`: Kirim Link → masukkan link dari inbox → Verifikasi → Apply Premium → Hasil Provider/Riwayat.
Setelah verifikasi berhasil dan provider mengembalikan idToken, bot otomatis mengirim satu POST apply
dengan `email` dan `idToken` untuk akun yang sama. Tombol Apply Premium juga dapat melanjutkan session
terverifikasi yang belum mengirim apply. Hasil sukses ditampilkan sebagai **Apply Premium: SUKSES**.

Tambahkan Railway variable:
```text
TOOLS_PROVIDER_APPLY_URL=https://alightfree.my.id/api/v1/apply-premium
TOOLS_PROVIDER_AUTH_MODE=x-api-key
```
Pertahankan `TOOLS_PROVIDER_API_KEY` sebagai Railway Secret yang sudah dikonfigurasi.
Endpoint Send Magic Link dan Verify Account tetap memakai variable sebelumnya.
`TOOLS_PROVIDER_APPLY_STATUS_URL` bersifat opsional dan bukan URL action apply.

Perbaikan:
- Kirim Link, Verifikasi, dan Apply Premium dicatat terpisah di Riwayat Tools.
- Status `success`, `failed`, `pending`, dan `unknown` mengikuti respons provider.
- Sukses verifikasi saja tidak dianggap sukses apply. HTTP 202 tetap diproses.
- POST aksi dikirim sekali, tanpa retry setelah timeout/5xx. Guard SQLite menahan replay/restart.
- Refresh Status hanya membaca endpoint status/riwayat; tidak mengirim apply lagi.
- Kuota menghitung setiap request HTTP aktual, termasuk polling/retry baca status.
- Navigasi `/tools` mempertahankan email, hasil, Flow ID, dan Provider Ref.
- Pagination Riwayat Tools kini memiliki handler.
- Riwayat Provision lama tetap dapat dibuka dan dicari dari Riwayat Tools.
- Link dan idToken disimpan sementara di memori; metadata serta wizard lain tetap persisten.
  Setelah restart/session kedaluwarsa, verifikasi ulang diperlukan bila apply belum dikirim.
- Schema 178 menambah meter request dan guard apply; tabel/data lama tetap dipertahankan.

Jika apply timeout, hasil menjadi **BELUM DIKETAHUI**. Periksa riwayat provider dan gunakan Refresh
Status bila endpoint baca tersedia. Bot mempertahankan guard sampai hasil bisa dipastikan.
Riwayat Tools adalah catatan bot dari respons API, bukan akses ke dashboard web provider.

Paket tetap berisi: `main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`,
dan `VARIABLE_RAILWAY.md`. Jalankan `python main.py` setelah variable dan Railway Volume siap.

Validasi revisi khusus tools: 45 uji regresi lulus, mencakup alur API, timeout, HTTP 202, 5xx,
kuota, replay, restart, migrasi, dan persistensi wizard command lain. Audit 25 nilai tombol
literal serta 11 template tombol dinamis di bagian `/tools` tidak menemukan handler yang hilang.
Seluruh 765 definisi dan 366 registrasi router v16.51 tetap tersedia; 686 definisi lainnya
identik dengan source original. Perubahan pada `SQLiteFSMStorage` dan `init_db` hanya menangani
session serta migrasi tools. Setelah blok
tools, penanganan penyimpanan tools, dan metadata versi dinormalisasi, seluruh source sama
persis dengan v16.51. Uji API menggunakan server simulasi lokal; apply pada akun provider asli
belum diuji.

## v16.51 — Apply Premium Provider Status URL

Peningkatan:
- variable baru `TOOLS_PROVIDER_APPLY_STATUS_URL`;
- khusus untuk membaca status/hasil Apply Premium dari provider;
- setelah verify selesai, bot otomatis polling endpoint status Apply Premium jika tersedia;
- hasil otomatis masuk ke `🚀 Apply Premium` dan `📋 Hasil Provider`;
- retry/polling mengikuti pengaturan v16.48;
- Flow ID dan Provider Ref tetap dipertahankan;
- URL action seperti `apply-premium` ditolak sebagai status URL.

Railway Variable baru:
```text
TOOLS_PROVIDER_APPLY_STATUS_URL=
```

Isi dengan endpoint provider yang bersifat status/result/history/lookup/check.

Schema tetap 177.
