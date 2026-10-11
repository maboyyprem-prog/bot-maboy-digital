# MaboyyDigital

Bot Telegram toko digital, versi **v16.89**. Python **3.10+**; diuji menggunakan Python 3.12.

## Upload GitHub / Railway

Unggah tujuh file langsung ke root repository, tanpa subfolder:
`main.py`, `bot.py`, `otp_smscode.py`, `requirements.txt`, `project_backup.py`, `.gitignore`, dan `README.md`.

Untuk update dari v16.88, unggah `bot.py`, `main.py`, `otp_smscode.py`, dan `README.md` dari paket ini, lalu redeploy. Untuk repository baru, gunakan seluruh tujuh file.

```bash
python -m pip install -r requirements.txt
python main.py
```

Start Command Railway: `python main.py`. Gunakan satu replica dan pasang Volume di `/data`; health check tersedia di `/health`.

## Variables

Isi melalui Railway Variables atau `.env` lokal. Ganti placeholder berikut dengan nilai milik sendiri:

```dotenv
BOT_TOKEN=TOKEN_BOT_TELEGRAM
ADMIN_ID=ID_TELEGRAM_OWNER
ADMIN_USERNAME=USERNAME_OWNER_TANPA_AT
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
```

`ADMIN_ID` harus berupa angka. `ADMIN_USERNAME` opsional. Path `/data` memerlukan Volume; untuk lokal dapat memakai `DB_PATH=shop.db` dan `BACKUP_DIR=backups`. Pertahankan database, kunci enkripsi, serta konfigurasi pembayaran/provider saat update.

Untuk mengaktifkan toko OTP:

```dotenv
SMSCODE_API_TOKEN=TOKEN_API_PROVIDER
SMSCODE_OTP_ENABLED=true
SMSCODE_WEBHOOK_PUBLIC_URL=https://bot-maboy-digital-production.up.railway.app/webhooks/smscode/otp
```

Gunakan domain deployment sendiri jika berbeda. Owner membuka `/otp` → **WEBHOOK** → **HUBUNGKAN WEBHOOK** → **TEST WEBHOOK**. Bot mengambil secret resmi provider secara otomatis; jika mengisi `SMSCODE_WEBHOOK_SECRET`, nilainya harus sama dengan secret tersebut. Polling tetap memantau SMS tanpa webhook.

`OTP_STORAGE_ENCRYPTION_KEY` opsional untuk enkripsi SMS; pertahankan nilainya saat redeploy. Untuk fitur AM, gunakan konfigurasi `/tools` yang sudah ada; tombol panduan login tidak memerlukan variabel baru.

Status toko OTP mengikuti ON/OFF yang disimpan owner dan tetap benar setelah restart. Pengaturan yang belum lengkap atau jeda layanan ditampilkan terpisah; stok diperiksa saat memilih nomor.

## Command

| Command | Fungsi |
|---|---|
| `/start` | Menu Awal dan belanja |
| `/otp` | Toko OTP user atau panel owner sesuai akses |
| `/tools` | Tools owner dan user yang diberi akses; tersedia Panduan Login AM via Email |
| `/owner` | Panel khusus owner |
| `/ping` | Status bot, khusus owner |

Saldo user digunakan bersama oleh fitur toko dan OTP. OTP mendukung **Buy Now (QRIS)** dan **Buy Saldo** melalui alur pembayaran existing; saldo provider hanya tampil pada owner.

## Backup

Gunakan `python project_backup.py --help` untuk full backup terenkripsi, verifikasi, dan restore. Simpan arsip serta kunci dekripsi secara terpisah di lokasi privat; sertakan database dan volume aplikasi. Restore ke lokasi baru dan jangan menimpa transaksi produksi.

Jangan unggah `.env`, token, database, session, log, atau backup privat ke GitHub.
