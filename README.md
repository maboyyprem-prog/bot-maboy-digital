# MaboyyDigital v16.94

Paket ringkas: **13 file**, langsung di root ZIP. Upload seluruh isinya ke root repository GitHub.

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
Verifikasi berhasil tersimpan di database dan bertahan setelah restart;
`SOSMED_API_CONTRACT_VERIFIED=true` tidak wajib untuk alur tombol ON ini.

Default `SOSMED_ENABLED=false` hanya untuk kondisi awal; pengaturan ON owner yang
tersimpan diprioritaskan. `SOSMED_REFILL_API_VERIFIED=false` tetap terpisah.
`BUZZERPANEL_CURRENCY`/`SOSMED_RATE_UNIT` boleh kosong jika API sudah menyebutnya.
Jika API tidak menyebut currency/unit, isi `IDR`/`1000` hanya setelah akun dan tarif
per 1.000 dikonfirmasi. Owner mendapat nama variabel yang perlu diperbaiki saat
pemeriksaan gagal. Redeploy setelah memperbarui Railway Variables.
Cancel dan tipe yang belum didokumentasikan tidak diaktifkan.

OTP tetap memakai Variables existing; jika webhook digunakan, alamatnya
`https://DOMAIN_BOT_ANDA/webhooks/smscode/otp`.

## Isi paket

Tujuh file Python aktif: `main.py`, `bot.py`, `otp_smscode.py`,
`sosmed_buzzerpanel.py`, `sosmed_ui.py`, `project_backup.py`, `bank_accounts.py`.
File pendukung: `requirements.txt`, `README.md`, `.env.example`, `.gitignore`,
`.python-version`, `railway.json`.

Tes, fixture bot lama, log, database, arsip backup, dan dokumentasi panjang
tersedia di paket lengkap/backup terpisah. Kode runtime sama dengan rilis
v16.94 yang lulus 315 tes mock dan 49 pemeriksaan transaksi.

Backup penuh: `python project_backup.py --help`. Simpan arsip dan kunci di luar
project, terpisah dan privat; sertakan volume/DB yang benar-benar tersedia.
Restore ke lokasi baru dahulu; jangan menimpa database produksi dengan snapshot lama.
Jangan upload `.env` asli, database, session, backup privat, atau kunci ke GitHub.
