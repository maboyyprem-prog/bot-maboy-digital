# MaboyyDigital v16.90

Paket ringkas: **12 file**, langsung di root ZIP. Upload seluruh isinya ke root repository GitHub.

## Jalankan

Python 3.12. Install `pip install -r requirements.txt`, lalu `python main.py`.
Railway: Start Command `python main.py`, health `/health`, satu replica.
Pasang Volume `/data`; Variables `DB_PATH=/data/shop.db`, `BACKUP_DIR=/data/backups`.
Pertahankan database, token, konfigurasi pembayaran, dan kunci enkripsi existing.
Hentikan poller lama sebelum menggunakan token yang sama pada Railway baru.

## Command

`/start` · `/otp` · `/sosmed` · `/tools` · `/owner` · `/ping`.
Panel Sosmed owner: `/sosmed admin`. Saldo user dipakai bersama oleh toko, OTP, dan Sosmed.

## Variabel

Isi `BOT_TOKEN` dan `ADMIN_ID` numerik melalui Railway Variables; daftar contoh ada di `.env.example`.
Sosmed memerlukan **BUZZERPANEL_API_KEY** dan **BUZZERPANEL_SECRET_KEY**.
Endpoint: `BUZZERPANEL_API_URL=https://buzzerpanel.id/api/json.php`.

Default `SOSMED_ENABLED=false`, `SOSMED_API_CONTRACT_VERIFIED=false`,
`SOSMED_REFILL_API_VERIFIED=false`. Respons akun, currency, satuan rate, dan form
harus cocok sebelum mengaktifkan `SOSMED_API_CONTRACT_VERIFIED=true` lalu
`/sosmed admin on`. `BUZZERPANEL_CURRENCY`/`SOSMED_RATE_UNIT` boleh kosong;
isi `IDR`/`1000` hanya setelah dikonfirmasi jika API tidak menyediakannya.
Cancel dan tipe yang belum didokumentasikan tidak diaktifkan.

OTP tetap memakai Variables existing; jika webhook digunakan, alamatnya
`https://DOMAIN_BOT_ANDA/webhooks/smscode/otp`.

## Isi paket

Enam file Python aktif: `main.py`, `bot.py`, `otp_smscode.py`,
`sosmed_buzzerpanel.py`, `sosmed_ui.py`, `project_backup.py`.
File pendukung: `requirements.txt`, `README.md`, `.env.example`, `.gitignore`,
`.python-version`, `railway.json`.

Tes, fixture bot lama, log, database, arsip backup, dan dokumentasi panjang
tersedia di paket lengkap/backup terpisah. Kode runtime sama dengan rilis
v16.90 yang lulus 256 tes mock dan 49 pemeriksaan transaksi.

Backup penuh: `python project_backup.py --help`. Simpan arsip dan kunci di luar
project, terpisah dan privat; sertakan volume/DB yang benar-benar tersedia.
Restore ke lokasi baru dahulu; jangan menimpa database produksi dengan snapshot lama.
Jangan upload `.env` asli, database, session, backup privat, atau kunci ke GitHub.
