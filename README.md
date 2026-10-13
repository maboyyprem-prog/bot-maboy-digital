# MaboyyDigital v17.03

Paket ringkas: **14 file**, langsung di root ZIP. Upload seluruh isinya ke root repository GitHub.

## Jalankan

Python 3.12. Install `pip install -r requirements.txt`, lalu `python main.py`.
Railway: Start Command `python main.py`, health `/health`, satu replica.
Pasang Volume `/data`; Variables `DB_PATH=/data/shop.db`, `BACKUP_DIR=/data/backups`.
Pertahankan database, token, konfigurasi pembayaran, dan kunci enkripsi existing.
Hentikan poller lama sebelum menggunakan token yang sama pada Railway baru.

## Command

`/start` · `/otp` · `/sosmed` · `/tools` · `/owner` · `/ping`.
`/sosmed` membuka panel owner untuk owner dan toko pembeli untuk user.
Owner bisa memilih **Menu Pembeli** untuk belanja memakai wallet pribadinya.
Saldo user dipakai bersama oleh toko, OTP, dan Sosmed.

Pembelian baru **/otp dan /sosmed hanya memakai saldo bot**. OTP memakai
**Buy Saldo**, Sosmed memakai **Bayar Saldo**. Jika saldo kurang, pilih
**Isi Saldo** melalui alur deposit existing, lalu pilih layanan kembali.
QRIS/payment gateway tetap tersedia untuk isi saldo dan checkout produk existing.
Invoice QRIS OTP yang sudah dibuat sebelum pembaruan tetap direkonsiliasi dengan
aturan lama; tombol QRIS lama tidak bisa membuat invoice pembelian baru.

## Harga dan layanan Sosmed

Modal & Jual berisi 6 layanan per halaman, nama singkat, dan tarif **per 1.000**.
Owner melihat modal terendah dulu; user melihat harga jual terendah dulu.
Pilih Kategori dan Refresh Layanan memakai katalog asli provider. Menu user
menyediakan pintasan **TikTok** dan **Instagram**, lalu kategori yang benar-benar
tersedia; platform kosong tidak dibuatkan layanan fiktif.
Tarif `price`/`rate` dibaca dengan Decimal tanpa dikalikan 1.000 saat sinkronisasi;
kolom yang bertentangan dinonaktifkan. Modal pecahan rupiah tampil tepat pada owner.
Modal order = tarif API × jumlah ÷ 1.000. Harga jual tetap mengikuti pengaturan
markup, minimum transaksi dan pembulatan existing. Buka detail layanan →
**Rincian Harga** untuk memeriksa penyebab harga jual; pengaturan tidak direset.
Detail user menyebut harga pembelian minimum, dan konfirmasi tetap memakai
jumlah nyata. Price sorting/refresh tidak mengurangi wallet atau membuat order.

Tombol **Cari Layanan** tersedia di menu awal user/owner, kategori, TikTok/Instagram,
Modal & Jual, daftar layanan dan favorit. Ketik kata kunci seperti
`followers`/`likes`; kategori/platform/favorit yang sedang dibuka tetap dipakai.
Owner mendapat hasil Modal & Jual. Gunakan **Hapus Pencarian** untuk kembali
ke daftar tanpa kata kunci/filter. Kembali dan Menu Awal tersedia pada form cari.

Menu kategori memiliki **Cari Kategori** di atas daftar. Ketik nama/kata kunci,
misalnya `follower`, `likes`, atau `livestream`, lalu pilih kategori hasil pencarian.
TikTok/Instagram tetap membatasi hasil ke platform yang dipilih. Daftar berisi
8 kategori per halaman; Kembali dari layanan mempertahankan pencarian dan halaman.
**Hapus Pencarian Kategori** menampilkan kembali daftar kategori pada platform yang
sama. Pencarian ini tersedia juga pada kategori harga dan markup owner.

## Waktu dan invoice foto

Semua waktu tampilan memakai **WIB (Asia/Jakarta)**: transaksi, kedaluwarsa,
riwayat, rekening, OTP, Sosmed, pemeriksaan API, dan laporan harian.
Timestamp internal tetap dipakai sesuai sistem existing; tidak perlu variabel `TZ` baru.
Pembayaran berhasil mengirim invoice PNG privat untuk produk, isi saldo, OTP,
dan Sosmed. Nominal, metode, invoice dan waktu berasal dari pembayaran nyata;
isi saldo memisahkan saldo masuk dengan total transfer/kode unik.
Invoice tersimpan dalam antrean SQLite, dilindungi lease, dan dicoba ulang
setelah gagal/restart. Gagal mengirim foto tidak membatalkan pembayaran atau
menambah saldo kembali. Transaksi lama tidak dikirim massal setelah update.
Telegram belum menjamin pengiriman tepat sekali jika respons sukses hilang.
Tidak ada variabel atau dependency baru; `payment_receipts.py` wajib ikut diupload.

## Rekening transfer

Buka `/owner` → Pengaturan Pembayaran → Rekening Transfer. Tambah/edit bank, nomor,
pemilik, dan catatan; periksa data lama/baru lalu tekan Simpan. Rekening dapat
aktif/nonaktif, dijadikan utama, atau dihapus dari daftar dengan soft delete.
Menu rekening ringkas dalam empat baris. Tambah/Edit membuka form bertahap dengan
tombol Kembali/Batal; input mengganti pesan form yang sama sebelum konfirmasi.
User memilih rekening aktif ketika deposit/checkout. Invoice menyimpan rekening
dan nomor salin sendiri; perubahan rekening tidak mengubah snapshot invoice.
Tidak ada variabel baru atau wallet baru untuk multi-rekening.

## Variabel

Isi `BOT_TOKEN` dan `ADMIN_ID` numerik melalui Railway Variables; daftar contoh ada di `.env.example`.
Sosmed memerlukan **BUZZERPANEL_API_KEY** dan **BUZZERPANEL_SECRET_KEY**.
Endpoint: `BUZZERPANEL_API_URL=https://buzzerpanel.id/api/json.php`.

Sesudah upload, ketik **`/sosmed`** sebagai owner. Gunakan tombol **Status API**
untuk memeriksa koneksi, lalu **Periksa & Buka Toko** untuk mengaktifkan toko.
Tombol berubah menjadi **Tutup Toko** saat aktif. Bot memeriksa profile/services
tanpa membuat order. Semua kontrol ini tersedia dalam menu yang sama.
Status API sekarang memeriksa koneksi saat dibuka, bukan hanya hasil terakhir.
Katalog besar kini dibaca bertahap melalui file sementara dengan batas khusus
64 MiB; decode berjalan pada worker. Respons order/profil tetap memakai batas lama.
Jika katalog gagal, saldo profil yang berhasil dibaca tetap tampil pada owner.
Validasi dilakukan per layanan: angka bulat seperti `100.0` dibaca dengan tepat,
duplikat identik digabung, dan entri invalid/ID konflik tidak dijual. Layanan valid
tetap diproses. Buka **Status API → Rincian Katalog** untuk ID, min/max, alasan
penolakan, serta jumlah layanan yang valid. Seluruh data invalid tetap menghentikan
pembelian; batas pecahan/format ambigu tidak dipaksakan menjadi jumlah.
Status menyebut **Profil/Katalog**, HTTP, dan penyebab yang aman: key ditolak,
izin IP, format respons, atau field saldo/harga yang perlu diperbaiki.
Saldo provider membaca `balance`/`saldo`; nilai hilang/bertentangan tidak dianggap nol.
Field pribadi pada Profile tidak ditampilkan dalam panel.
Katalog standar `id/price/note` tanpa `type` memakai form target + jumlah sesuai API;
catatan `note` tampil sebagai panduan username/URL. Layanan khusus yang belum jelas
bisa diatur owner: Modal & Jual → pilih layanan → **Tipe/Input** → konfirmasi.
Status `Success` berarti selesai, `Error` berarti gagal; refund tetap perlu bukti.
Daftar layanan user/owner berisi **6 pilihan per halaman**, dengan Sebelumnya,
Berikutnya, detail, dan **Refresh Layanan**. Refresh memperbarui harga, min/max,
catatan dan ketersediaan dari API; katalog juga diperbarui mengikuti TTL existing.
Harga/min/max tetap diperiksa ulang sebelum pembayaran. Wallet tidak berubah
karena membuka halaman atau memakai Refresh.
Verifikasi berhasil tersimpan di database dan bertahan setelah restart;
`SOSMED_API_CONTRACT_VERIFIED=true` tidak wajib untuk alur tombol ON ini.

Default `SOSMED_ENABLED=false` hanya untuk kondisi awal; pengaturan ON owner yang
tersimpan diprioritaskan. `SOSMED_REFILL_API_VERIFIED=false` tetap terpisah.
Jika Profile tidak menyebut mata uang, buka **Status API → Mata Uang & Satuan**:
konfirmasi **IDR** setelah saldo akun bertanda Rp, dan **/ 1.000** setelah kolom
harga layanan menyatakan tarif per 1.000. Kedua konfirmasi terpisah, tersimpan,
dan tidak memakai nilai saldo pada foto. Lalu tekan **Periksa & Buka Toko**.
Harga per 1.000 yang belum diketahui perlu dicek pada daftar layanan provider.
Alternatif Variables existing: `BUZZERPANEL_CURRENCY=IDR`, `SOSMED_RATE_UNIT=1000`;
keduanya opsional bila API/konfirmasi owner sudah menyebutnya. Nilai eksplisit API
tetap diperiksa, dan pergantian akun API memerlukan konfirmasi baru.
Cancel dan tipe yang belum didokumentasikan tidak diaktifkan.

OTP tetap memakai Variables existing; jika webhook digunakan, alamatnya
`https://DOMAIN_BOT_ANDA/webhooks/smscode/otp`.

## Isi paket

Delapan file Python aktif: `main.py`, `bot.py`, `otp_smscode.py`,
`sosmed_buzzerpanel.py`, `sosmed_ui.py`, `project_backup.py`, `bank_accounts.py`,
`payment_receipts.py`.
File pendukung: `requirements.txt`, `README.md`, `.env.example`, `.gitignore`,
`.python-version`, `railway.json`.

Tes, fixture bot lama, log, database, arsip backup, dan dokumentasi panjang
tersedia di paket lengkap/backup terpisah. Kode runtime sama dengan rilis
v17.03; hasil verifikasi dan backup tersedia dalam laporan rilis terpisah.

Backup penuh: `python project_backup.py --help`. Simpan arsip dan kunci di luar
project, terpisah dan privat; sertakan volume/DB yang benar-benar tersedia.
Restore ke lokasi baru dahulu; jangan menimpa database produksi dengan snapshot lama.
Jangan upload `.env` asli, database, session, backup privat, atau kunci ke GitHub.
