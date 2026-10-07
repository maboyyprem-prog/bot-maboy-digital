# Maboyy Digital Bot

**Versi aktif:** v16.56 — VIP khusus `/tools`, Magic Link sampai apply sukses, dan perbaikan input slot.

## v16.56 — VIP /tools, Magic Link, dan Input Slot Pre-Order

Owner tetap mendapatkan panel `/tools` lengkap. Menu baru **👑 VIP /tools** digunakan
untuk memilih user yang boleh menjalankan Magic Link. Status VIP ini khusus untuk `/tools`;
aturan akses command lain dan level member berdasarkan belanja tetap seperti sebelumnya.
Izin disimpan di database sehingga tetap berlaku setelah restart. User yang belum dipilih
owner tidak dapat memakai fitur `/tools` dan mendapat pemberitahuan pembatasan akses.

Cara memberi akses:
1. Owner membuka `/tools` → **👑 VIP /tools**.
2. Pilih **👤 Pilih User Bot**, atau **➕ Tambah User dengan ID** untuk mengirim ID Telegram/
   meneruskan pesan user yang identitas pengirimnya tersedia.
3. Tekan **✅ Jadikan VIP /tools**. Izin dapat dihentikan melalui **🚫 Cabut VIP /tools**.

User VIP membuka `/tools` di chat pribadi dan melihat status **VIP KHUSUS /TOOLS** serta
pesan **“Gunakan fitur dengan bijak. Pastikan email dan link yang Anda kirim sudah benar.”**
Keyboard toko disembunyikan dan menu tools hanya berisi **📧 Magic Link**.
Alurnya: kirim email → konfirmasi pengiriman → salin URL dari
inbox ke bot → **✅ Proses Magic Link** → verifikasi dan Apply Premium otomatis.
User tidak mendapatkan tombol Verifikasi, Apply, provider/config, history, atau panel owner
sebagai menu terpisah. Penolakan akses juga berlaku untuk tombol owner yang diteruskan.

**⭐ Rating Toko** baru muncul setelah apply sukses tercatat dari provider. User dapat memilih
1–5 bintang, satu kali per flow sukses. Rating masuk ke ringkasan Rating Toko dan daftar
penilaian owner; rating pesanan lama tetap tersedia. Tidak dibuat order/pembayaran palsu.
Verifikasi sukses saja, hasil pending, timeout, dan status belum diketahui tidak membuka rating.

Tombol proses terikat pada user dan flow yang sama. Request POST tidak diulang otomatis;
status pending/unknown dipertahankan. Membuka Magic Link saat hasil belum pasti hanya
membaca endpoint status jika tersedia, tanpa mengulang apply. Owner dapat mencabut izin;
akses diperiksa lagi sebelum setiap tahap berikutnya. Request yang sudah terkirim ke
provider tidak dapat dibatalkan dengan pencabutan izin.

Schema **179** menambahkan `tools_user_access` dan `tools_user_reviews`; tabel/data lama
tetap dipertahankan dan migrasi berjalan saat startup. Tidak ada variable atau dependensi
baru. Link dan idToken tetap hanya disimpan sementara di memori serta tidak ditampilkan
ke user. Perbaikan stok Famhead v16.55 tetap tersedia.

Memperbaiki kasus Tambah Slot Pre-Order → kirim `4` yang sebelumnya membuka kartu produk.
Shortcut produk angka 1–25 sekarang hanya berjalan saat tidak ada wizard/input aktif.
Angka dalam Tambah Custom diteruskan ke handler slot, disimpan, dan ditampilkan pada
konfirmasi jumlah slot. Input angka untuk durasi flash sale, jumlah akun/stok, dan alert
stok juga sampai ke wizard masing-masing. Shortcut produk saat idle dan navigasi keluar
dari unggah bukti pembayaran tetap tersedia; nama/menu command lain tidak diganti.

Tombol nominal saldo yang sudah terpilih (`noop`) kini menjawab callback tanpa memunculkan
peringatan kedaluwarsa, mengubah nominal, atau membersihkan session.

Validasi v16.56: **129 uji regresi** dan **49 pemeriksaan runtime** lulus, termasuk alur
VIP sampai Apply Premium, pencabutan akses, rating, dan input slot melalui router aiogram
asli. Audit mencakup **299 callback**, **87 handler pesan**, **216 nilai tombol literal**,
serta **240 template tombol dinamis**; tidak ditemukan referensi handler/state yang hilang.
Seluruh definisi fitur v16.55 dipertahankan. Pengujian provider menggunakan API lokal dan
respons Telegram simulasi; apply pada akun asli serta deployment Railway belum diuji.

## v16.55 — Perbaikan Stok Famhead

Memperbaiki `ValidationError` ketika menekan +1/+5/+10 di Atur Slot Pre-Order/Famhead.
Callback Telegram tidak lagi diubah setelah stok disimpan. Jumlah slot di layar langsung
diperbarui; `reserved_stock` tetap diperhitungkan saat menampilkan slot tersedia.

Tambah Custom tetap menerima 1–10000 slot. Tombol Kembali membatalkan input custom agar
pesan angka berikutnya tidak menambah stok di luar wizard. Callback/input/session yang
tidak valid dan produk/varian nonaktif ditolak sebelum mengubah stok.

Dua tombol navigasi stok lama yang juga mengubah callback diperbaiki. Tombol tambah stok
lama untuk Famhead/pre-order membuka menu slot; produk ready tetap memakai menu akun/stok
yang sudah ada. Penambahan slot dilakukan dalam transaksi SQLite dan menolak angka yang
akan melebihi batas penyimpanan.

Nama command, flow pembayaran, provider `/tools`, dependensi, serta schema **178** tetap
dipertahankan. Tidak ada variable baru. Upload keenam file dari paket yang sama, lalu
redeploy dengan Start Command `python main.py`.

Catatan stok versi sebelumnya: error muncul sesudah stok sudah disimpan. Periksa jumlah
aktual di Atur Stok sebelum menambahkan ulang agar jumlah yang diinginkan tidak terlampaui.

Validasi v16.55: **86 uji regresi** dan **49 pemeriksaan runtime** lulus, termasuk 18 uji
stok/callback dengan model aiogram asli dan respons Telegram simulasi. Kasus pada gambar
`ownerposlotadd:12:5` diuji sampai stok tersimpan dan tampilan diperbarui. Audit 285 callback,
84 handler pesan, serta 227 template tombol dinamis tidak menemukan handler atau state hilang.
Delapan fungsi stok diperbaiki dan dua helper stok ditambah; kode runtime lainnya identik
dengan v16.54 setelah metadata versi dinormalisasi. Deployment Railway belum diuji pada sesi ini.

## v16.54 — Versi Paket dan Panduan Upload

Paket ini menyertakan panduan enam file untuk GitHub serta penjelasan hubungan pembayaran
dan Apply Premium. Versi launcher, source bot, dan nama ZIP diselaraskan menjadi v16.54.
Tidak ada perubahan flow command/provider atau schema database; schema tetap 178.

Setiap peningkatan berikutnya menaikkan nomor rilis, misalnya v16.54 → v16.55 → v16.56.
Versi harus sama pada `BOT_VERSION`, `EXPECTED_SOURCE_VERSION`, `EXPECTED_VERSION` launcher,
versi aktif panduan, dan nama ZIP `MaboyyDigital_v<versi>.zip`.
Nama enam file di dalam ZIP tetap sama agar import serta deployment tetap berfungsi.
Paket ZIP lama tetap dipertahankan; perubahan rilis dicatat di panduan.

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

## Panduan Upload GitHub

Ekstrak ZIP, lalu upload keenam file berikut langsung ke root repository, tanpa folder tambahan:

| File | Fungsi |
| --- | --- |
| `main.py` | Launcher; Start Command Railway: `python main.py`. |
| `bot.py` | Seluruh fitur dan handler bot, termasuk tools/provider. |
| `requirements.txt` | Daftar dependensi Python yang di-install saat build. |
| `.env.example` | Contoh nama variable; tidak diisi token/API key asli. |
| `README.md` | Panduan penggunaan, upload, dan catatan versi. |
| `VARIABLE_RAILWAY.md` | Panduan variable serta penyimpanan Railway. |

Jika repository lama sudah memiliki file tersebut, perbarui isinya dengan nama yang sama.
Upload `main.py` dan `bot.py` dari versi yang sama agar pemeriksaan versi launcher lulus.
ZIP distribusi tidak perlu di-upload sebagai source aplikasi.

Jangan upload `.env` berisi credential, token/API key asli, database `shop.db`/`*.sqlite`, file
SQLite `-wal`/`-shm`, backup database, log runtime, atau cache `__pycache__`/`*.pyc`.
Simpan credential di Railway Variables/Secrets. `.env.example` tidak otomatis mengisi variable
Railway. Database produksi dan backup tetap berada pada Railway Volume `/data`.

## Pembayaran dan Apply Premium

Pada v16.56, pembayaran checkout belum memicu Apply Premium otomatis.
Order yang dikonfirmasi lunas tetap mengikuti fulfillment toko yang sudah ada: pengiriman
akun dari stok untuk produk ready, atau pemrosesan owner untuk produk pre-order.

Apply Premium sudah tersedia dalam `/tools` untuk owner dengan alur:
Kirim Link → masukkan link dari inbox → Verify Account → idToken → POST Apply Premium → Riwayat.
Konfigurasi provider wajib lengkap; respons provider menentukan sukses/gagal/diproses/belum
diketahui. Keberhasilan apply pada akun asli belum diuji pada sesi pengembangan ini.

User yang diberi izin owner pada v16.56 dapat menjalankan flow yang sama melalui menu
Magic Link sederhana sampai Apply Premium otomatis dan Rating Toko setelah sukses.

Otomatisasi setelah pembayaran memerlukan pengaitan order lunas dengan email terverifikasi
serta flow apply; pengaitan ini belum diterapkan pada v16.56. Payment success dan Apply Premium
success adalah status terpisah.

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
