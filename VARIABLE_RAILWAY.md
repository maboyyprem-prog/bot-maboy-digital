# Migrasi dan Variables Railway — Maboyy Digital v16.74

Dokumen ini panduan manual, bukan skrip deploy/restore. Paket source tidak memuat database atau nilai rahasia produksi.

## /ping dan paket Railway v16.71

`/ping` tetap khusus owner. Informasi lama tetap tersedia; tambahan menampilkan durasi proses bot sejak dijalankan dan sisa hari menuju tanggal paket yang diisi owner. Restart/redeploy mengulang uptime proses. Dua Variables baru berikut opsional dan tidak mengganti Variables lama:

| Variable baru | Nilai dan arti |
| --- | --- |
| `HOSTING_PLAN_NAME` | Nama paket, misalnya `Hobby`, `Pro`, atau `Trial`; kosong berarti belum diatur. |
| `HOSTING_PLAN_EXPIRES_AT` | Tanggal acuan batas paket/trial yang owner lihat di dashboard Railway. Contoh `2026-11-08` berlaku sampai akhir hari tersebut dalam WIB. Bisa juga waktu ISO, misalnya `2026-11-08T18:00:00+07:00` atau `2026-11-08T11:00:00Z`; waktu tanpa offset dibaca sebagai WIB. |

Isi melalui Variables service baru/lama sesuai kebutuhan, tanpa menyalin rahasia ke GitHub. Kosong/format salah menampilkan informasi belum diatur/tidak valid, tanpa membuat klaim sisa 0 hari. Jika tanggal sudah lewat, ditampilkan 0 hari dan keterangan tanggal lewat. Durasi sisa menunjukkan hari/jam/menit; kurang dari 24 jam diberi keterangan kurang dari 1 hari. Penghitungan tidak mengubah pembayaran, data, atau menghentikan bot.

Railway tidak mencantumkan nama paket/tanggal berakhir dalam [metadata environment otomatis](https://docs.railway.com/variables/reference). Ini tanggal manual, bukan pembacaan billing/credit Railway. [Paket berbayar memakai tagihan bulanan](https://docs.railway.com/pricing/plans): tanggal perpanjangan bukan berarti service otomatis kedaluwarsa. Jika memakai tanggal tagihan berikutnya sebagai acuan, beri nama paket jelas dan perbarui tanggal setelah perpanjangan. [Trial dapat berakhir lebih awal saat kredit habis](https://docs.railway.com/pricing/free-trial); `/ping` tidak membaca saldo kredit atau menjamin bot aktif sampai tanggal tersebut.

## Persiapan migrasi v16.70

### 1. File untuk GitHub: tepat 6

| File di root repository | Kegunaan |
| --- | --- |
| `main.py` | Launcher Railway; Start Command `python main.py`. |
| `bot.py` | Semua fitur bot, pembayaran, database dan Full Backup lama. |
| `requirements.txt` | Dependency Python. |
| `.env.example` | Semua nama konfigurasi; nilai contoh bukan pengganti Variables lama. |
| `README.md` | Panduan singkat. |
| `VARIABLE_RAILWAY.md` | Daftar Variables dan panduan migrasi/restore ini. |

Gunakan keenam file v16.71 dari paket yang sama, tanpa folder. Jangan upload `shop.db`, file `*.db-wal`/`*.db-shm`, Full Backup, ZIP, `.env` asli, token/API key, log, cache, atau kunci privat. Upload dengan daftar file di atas; hindari `git add .` dari folder kerja yang berisi data.

### 2. Railway Variables yang dipindahkan secara manual

Salin **nilai asli setiap Variable manual yang sudah ada** langsung dari Railway lama ke Variables Railway baru melalui akun sendiri. Nilai aslinya tidak tercantum di dokumen/paket ini dan tidak perlu dikirim ke chat. Jangan mengubah nama, nilai, status aktif, atau kondisi kosong/tidak diisi pada service lama. Jangan mengimpor `.env.example` sebagai pengganti konfigurasi produksi.

Inventaris kode: **61 nama**, terdiri dari **56 konfigurasi aplikasi/port** dan **5 metadata otomatis**. Tidak semuanya wajib diisi: grup opsional mengikuti fitur yang sudah aktif pada bot lama. Dua nama baru khusus `/ping` opsional; seluruh 59 nama sebelumnya dipertahankan.

| Grup | Nama yang diperiksa/disalin jika dipakai |
| --- | --- |
| Telegram | `BOT_TOKEN`, `ADMIN_ID`, `ADMIN_USERNAME`, `PAYMENT_NOTE` |
| Channel | `REQUIRED_CHANNEL_ID`, `REQUIRED_CHANNEL_URL`, `REQUIRED_CHANNEL_NAME`, `STOCK_CHANNEL_ID` |
| Database dan backup | `DB_PATH`, `BACKUP_DIR`, `BACKUP_INTERVAL_HOURS`, `BACKUP_RETENTION` |
| Reservasi | `ORDER_RESERVATION_MINUTES` |
| Pembayaran otomatis | `SHOPEEPAY_ENABLED`, `SHOPEEPAY_BASE_URL`, `SHOPEEPAY_CLIENT_ID`, `SHOPEEPAY_CLIENT_SECRET`, `SHOPEEPAY_MERCHANT_ID`, `SHOPEEPAY_STORE_ID`, `SHOPEEPAY_TERMINAL_ID`, `SHOPEEPAY_PRIVATE_KEY`, `SHOPEEPAY_PUBLIC_KEY`, `PUBLIC_BASE_URL` |
| Provider /tools | `TOOLS_PROVIDER_ENABLED`, `TOOLS_PROVIDER_NAME`, `TOOLS_PROVIDER_AUTH_MODE`, `TOOLS_PROVIDER_API_KEY`, `TOOLS_PROVIDER_MAGICLINK_URL`, `TOOLS_PROVIDER_VERIFY_URL`, `TOOLS_PROVIDER_APPLY_URL`, `TOOLS_PROVIDER_APPLY_STATUS_URL`, `TOOLS_PROVIDER_STATUS_URL`, `TOOLS_PROVIDER_PROVISION_URL` |
| Batas dan sesi /tools | `TOOLS_PROVIDER_TIMEOUT_SECONDS`, `TOOLS_PROVIDER_APPLY_TIMEOUT_SECONDS`, `TOOLS_PROVIDER_MAX_RETRIES`, `TOOLS_PROVIDER_REQUEST_COOLDOWN_SECONDS`, `TOOLS_PROVIDER_MAX_RESPONSE_CHARS`, `TOOLS_PROVIDER_HOURLY_LIMIT`, `TOOLS_PROVIDER_REQUESTS_PER_ACCOUNT`, `TOOLS_SESSION_EXPIRY_MINUTES`, `TOOLS_EMAIL_LOCK_SECONDS`, `TOOLS_PROVIDER_STATUS_CACHE_SECONDS`, `TOOLS_PROVIDER_POLL_ATTEMPTS`, `TOOLS_PROVIDER_POLL_INTERVAL_SECONDS`, `TOOLS_PROVIDER_TEMP_RETRIES` |
| Temp Mail dan aktivasi | `TEMPMAIL_ENABLED`, `TEMPMAIL_PROVIDER`, `TEMPMAIL_TIMEOUT_SECONDS`, `TEMPMAIL_ENCRYPTION_KEY`, `TOOLS_AUTO_AM_MAIL_PROVIDER`, `TOOLS_AUTO_AM_MAIL_WAIT_SECONDS`, `TOOLS_AUTO_AM_POLL_SECONDS` |
| HTTP | `PORT` — cocokkan dengan target port service; pertahankan override manual jika ada, atau gunakan nilai Railway. |
| Informasi paket di /ping (opsional) | `HOSTING_PLAN_NAME`, `HOSTING_PLAN_EXPIRES_AT` — salin jika sudah diisi manual; bukan metadata otomatis Railway. |

**Wajib:** token bot yang sama, owner yang sama, `DB_PATH` ke Volume persisten. Untuk Volume `/data`: `DB_PATH=/data/shop.db` dan `BACKUP_DIR=/data/backups`. Jika lokasi lama berbeda, catat lokasi sumber lama; hanya path service baru yang disesuaikan. Pertahankan interval, retention, reservasi dan semua batas lama, meskipun berbeda dari contoh.

**Kunci enkripsi inbox:** pertahankan persis `TEMPMAIL_ENCRYPTION_KEY` lama. Jika sebelumnya kosong/tidak ada, bot menggunakan `BOT_TOKEN` sebagai kunci; jangan mengganti token atau membuat kunci baru saat migrasi. Token Telegram yang sama juga diperlukan agar `file_id` QRIS, bukti dan file akun lama tetap dapat digunakan.

**Pembayaran:** salin semua credential gateway yang dipakai, termasuk bentuk multiline/literal `\n` pada private/public key. Jika tetap memakai domain yang sama, pertahankan `PUBLIC_BASE_URL`; jika domain baru, isi URL baru hanya pada service baru dan ubah callback provider menjadi `https://DOMAIN-BARU/shopeepay/callback`. Nilai ini ikut dalam verifikasi tanda tangan. Bot tidak mendaftarkan callback provider secara otomatis. Pertahankan `SHOPEEPAY_ENABLED` lama; gunakan credential/akses provider yang sama. Jangan alihkan callback sebelum database baru siap.

**Metadata otomatis — jangan disalin dari deployment lama:** `RAILWAY_DEPLOYMENT_ID`, `RAILWAY_REPLICA_ID`, `RAILWAY_GIT_COMMIT_SHA`, `RAILWAY_ENVIRONMENT_NAME`, `RAILWAY_SERVICE_NAME`. Railway menyediakan nilai baru. Shared/reference Variables lama perlu diarahkan ke project/service baru dan hasil nilainya diperiksa secara pribadi, bukan menyalin referensi ID lama secara buta.

**Infrastruktur opsional:** jika sudah digunakan, pindahkan konfigurasi yang diperlukan untuk `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `http_proxy`, `https_proxy`, `no_proxy`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `NETRC`. Ini dukungan library/jaringan, terpisah dari 61 nama aplikasi/metadata; path sertifikat/NETRC harus benar-benar tersedia pada service baru. Tidak perlu menambahkan nilai kosong. Metadata Volume, token login CLI, dan variable build Railway bukan credential bot untuk dipindahkan.

### 3. Database yang di-restore: seluruh shop.db

Full Backup lama adalah `/owner` → **Sistem** → **📦 Backup Project**. Fitur yang sama tetap digunakan; tidak ada fitur backup duplikat. ZIP privat berisi snapshot utuh bernama **`shop.db`**, source yang tersedia dan `BACKUP_MANIFEST.txt`. **Backup Database** dan backup otomatis juga menyimpan seluruh SQLite, bukan hanya produk.

Snapshot menggunakan SQLite Backup API, sehingga transaksi yang sudah commit di WAL ikut tersalin. Semua tabel ikut: customer/user, saldo dan ledger, produk/varian/stok/reservasi/akun, order/transaksi/topup, voucher, rating, pengaturan pembayaran/QRIS, sesi/FSM, VIP /tools, Temp Mail dan job aktivasi. Pengaturan kode unik yang sudah tersimpan dipertahankan saat startup v16.70.

Backup v16.70 memeriksa integritas dan mencatat SHA-256, ukuran, schema serta jumlah baris tiap tabel di manifest. Backup lama tetap bisa dipakai setelah pemeriksaan lokal. Informasi "backup terakhir" ditulis setelah snapshot dibuat, sehingga metadata laporan backup terbaru dapat berbeda tanpa kehilangan data toko.

ZIP Full Backup/database **tetap mengandung data privat**, termasuk akun stok dan credential mailbox yang disimpan bot. `.env` dan Railway Secrets eksternal tidak disertakan. Jangan upload ZIP Full Backup ke GitHub. Foto Telegram dan inbox provider eksternal bukan file yang disalin oleh SQLite; database menyimpan ID/credential/link, dan aksesnya bergantung pada token serta masa simpan layanan.

### 4. Langkah migrasi manual yang aman

1. Catat total customer, saldo/ledger, produk, stok/reservasi, pesanan/transaksi dan pengaturan penting; simpan privat. Salin Variables. Aktifkan Maintenance lama; selesaikan/review pesanan pending tanpa menghapus histori. Simpan Full Backup awal dan Volume lama untuk rollback. **Pastikan database lama memang berada pada Volume.** Jika masih berada di disk container, jangan mengubah/redeploy deployment lama: ekspor Full Backup privat terlebih dahulu dari container yang sama melalui [SSH/SCP Railway](https://docs.railway.com/cli/ssh), hentikan penerimaan transaksi dan rekonsiliasi transaksi sejak snapshot sebelum berpindah. Metode idle berikut hanya untuk database pada Volume persisten.
2. Hentikan **proses bot** lama sebelum snapshot final. Maintenance saja belum menghentikan callback pembayaran/background worker. Untuk database lama pada Volume, owner dapat sementara mengganti Start Command service lama menjadi `python -c "import time; time.sleep(86400)"`, menonaktifkan healthcheck sementara, lalu menjalankan deployment idle itu secara manual. Pastikan `main.py`/polling/worker lama sudah berhenti. Variables lama tidak perlu diubah. SSH hanya menjalankan fungsi backup satu kali, tanpa `bot.main()`/`init_db()`:

   ```sh
   railway login
   railway link
   railway status
   railway ssh -- python -c 'import bot; print(bot.create_project_backup()[0])'
   ```

   Pilih project/service/environment **lama**. Catat nama ZIP yang dihasilkan. Bila `BACKUP_DIR=/data/backups`, unduh melalui root Volume:

   ```sh
   railway volume files list /backups
   railway volume files download /backups/NAMA-ZIP-FINAL.zip ./FullBackup.zip
   ```

   Ganti nama contoh dengan nama asli. Jangan menyalin `shop.db` mentah dari bot yang masih berjalan, karena data commit terbaru dapat berada di WAL. Simpan backup secara privat sebelum mengubah/menghentikan container tanpa Volume.

3. Di komputer pribadi, periksa ZIP, ekstrak hanya `shop.db`, validasi SQLite dan checksum jika tersedia. Jalankan dari folder privat baru yang belum berisi `shop.db`:

   ```sh
   python - <<'PY'
   import hashlib, pathlib, sqlite3, zipfile
   target = pathlib.Path('shop.db')
   assert not target.exists(), 'Gunakan folder privat baru; jangan timpa database.'
   with zipfile.ZipFile('FullBackup.zip') as archive:
       assert archive.testzip() is None, 'ZIP rusak.'
       raw = archive.read('shop.db')
       manifest = archive.read('BACKUP_MANIFEST.txt').decode('utf-8')
   digest = hashlib.sha256(raw).hexdigest()
   expected = [line.split(': ', 1)[1] for line in manifest.splitlines()
               if line.startswith('Database SHA256: ')]
   assert not expected or expected == [digest], 'Checksum berbeda.'
   with target.open('xb') as handle:
       handle.write(raw)
   conn = sqlite3.connect('file:shop.db?mode=ro', uri=True)
   assert conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
   tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
   for (name,) in tables:
       quoted = '"' + name.replace('"', '""') + '"'
       print(name, conn.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0])
   conn.close()
   print('SHA256:', digest)
   PY
   ```

   Catat checksum dan jumlah baris privat. Jika arsip bukan Backup Project tetapi file `.db` dari Backup Database, gunakan snapshot itu sebagai `shop.db` dan jalankan pemeriksaan SQLite yang sama. Jangan gabungkan tabel atau membuat database kosong.

4. Buat repository GitHub baru berisi enam source; siapkan service Railway baru dan Volume kosong mount **`/data`**. Tunda start/autodeploy bot baru sampai restore selesai. Isi Variables asli melalui UI privat; belum menjalankan `python main.py`. Volume tersedia saat runtime, bukan build/pre-deploy; jangan meletakkan restore pada Build/Pre-deploy Command.
5. Pada terminal pribadi, hubungkan CLI ke **project/service/environment baru**, lalu periksa target sebelum upload. Dengan CLI terbaru, pengelolaan file Volume mendukung upload/download; remote `/shop.db` berarti `/data/shop.db` pada Volume mount `/data`:

   ```sh
   railway link
   railway status
   railway volume list
   railway volume files list /
   railway volume files upload ./shop.db /shop.db
   railway volume files download /shop.db ./shop-restored-check.db
   python -c "import hashlib,pathlib; a=pathlib.Path('shop.db').read_bytes(); b=pathlib.Path('shop-restored-check.db').read_bytes(); assert hashlib.sha256(a).digest()==hashlib.sha256(b).digest(); print('Checksum restore cocok')"
   ```

   Pilih Volume baru yang benar jika CLI bertanya. Jangan memakai `--overwrite` untuk database yang sudah ada; hentikan dan periksa target terlebih dahulu. Volume lama tetap disimpan. Perintah tersedia dalam [dokumentasi resmi Railway Volume CLI](https://docs.railway.com/cli/volume); [mount Volume](https://docs.railway.com/volumes) bersifat persisten.
6. Setelah file cocok, pastikan bot lama tetap berhenti. Owner baru menjalankan satu instance dengan Start Command `python main.py` dan healthcheck `/health`. Arahkan domain/callback gateway ke service baru bila diperlukan, lalu cek `/ping`, Diagnostik/Launch Readiness, jumlah customer/saldo/stok/transaksi/pengaturan dan menu /start, /owner, /tools. Database akan membuka data lama, bukan membuat toko kosong.

Pesanan expired dapat diproses sesuai waktu reservasi lama setelah startup; jangan menyebut perubahan status yang wajar ini kehilangan data. Tinjau pesanan bayar/pending dengan provider sebelum membuka toko; callback pembayaran yang terjadi saat downtime memerlukan retry/reconciliation provider. Gunakan satu percobaan pembayaran terkontrol sesuai prosedur provider untuk memeriksa callback dan pemenuhan, bukan membuat tagihan duplikat.

**Rollback:** sebelum toko baru menerima transaksi, hentikan service baru lalu kembalikan service lama dengan Start Command/healthcheck/domain lama. Setelah ada transaksi baru, jangan langsung memakai snapshot lama karena akan menghilangkan saldo/order terbaru; hentikan penulis baru, ambil snapshot final baru dan rekonsiliasi data dahulu. Jangan menghapus Volume, backup, atau deployment lama sebelum verifikasi selesai.

### 5. Pengujian paket

**14 uji backup/restore baru lulus** pada database sementara: snapshot penuh, data commit di WAL, integritas/checksum, restore ke lokasi Volume simulasi dan dua kali startup. Seluruh 48 tabel aplikasi, tabel ekstensi simulasi, schema/index dan data saldo/stok/transaksi/pengaturan/sesi tetap sama. Job AM dipulihkan tanpa mengulang pengiriman link/apply yang sudah dijalankan. Kredensial inbox terenkripsi terbuka dengan kunci/token lama; perubahan kunci ditolak. Instruksi ekstraksi/verifikasi pada langkah 3 juga dijalankan dengan snapshot simulasi dan menghasilkan database yang identik.

Total **852 kasus unik lulus**: 825 regresi fitur lama dan 27 kasus migrasi, melalui suite lengkap 851 kasus serta satu kasus tambahan pemulihan inbox terenkripsi. **49 pemeriksaan runtime lulus**, termasuk schema, launcher/dependency, isolasi demo dan callback; tidak ada fungsi lama atau nama Variable lama yang dihapus. Bug transaksi SQLite saat retry pengiriman akun yang sudah dialokasikan juga diperbaiki; callback ulang tidak menambah debit/alokasi.

Audit Variables mengecek seluruh 59 nama, kelengkapan dan kompatibilitas nilai contoh lama. Alur callback/pembayaran diuji dengan simulasi; tidak ada deploy, restore, pengiriman Telegram atau pembayaran produksi otomatis.

Pembayaran otomatis dipertahankan di source; keberhasilan produksi tetap memerlukan credential lama, akses jaringan, domain/signature/callback provider dan satu instance yang benar. Panduan ini tidak menyatakan Railway/provider produksi sudah diuji langsung.

## Referensi dan riwayat konfigurasi lama

Bagian berikut dipertahankan sebagai referensi historis. Daftar migrasi v16.70 di atas dan `.env.example` adalah inventaris kode saat ini. Catatan versi lama tentang variable "tidak digunakan" jangan dijadikan alasan menghapus Variables lama saat migrasi: `TOOLS_PROVIDER_STATUS_URL` dan `TOOLS_PROVIDER_PROVISION_URL` tetap memiliki jalur kompatibilitas.

# Panduan Lengkap Variable Railway — Maboyy Digital

File ini hanya berisi dokumentasi variable. Tidak digunakan langsung oleh bot.

---

## 1. Variable Utama Telegram Bot

### BOT_TOKEN
Token bot dari BotFather.

Contoh:
```env
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Wajib: Ya

Catatan:
- Jangan bagikan token ke orang lain.
- Jangan upload token asli ke GitHub.

---

### ADMIN_ID
Telegram User ID owner/admin utama bot.

Contoh:
```env
ADMIN_ID=123456789
```

Wajib: Ya

Digunakan untuk:
- akses `/owner`
- menerima backup otomatis
- menerima notifikasi order tertentu

---

### ADMIN_USERNAME
Username Telegram owner tanpa tanda `@`.

Contoh:
```env
ADMIN_USERNAME=maboyy
```

Wajib: Disarankan

Digunakan untuk tombol:
- Hubungi Owner

---

### PAYMENT_NOTE
Catatan pembayaran yang tampil ke user.

Contoh:
```env
PAYMENT_NOTE=Silakan scan QRIS dan transfer sesuai total pembayaran.
```

Wajib: Tidak

---

## 2. Verifikasi Channel

### REQUIRED_CHANNEL_ID
Channel yang wajib diikuti user sebelum menggunakan bot.

Untuk channel publik:
```env
REQUIRED_CHANNEL_ID=@maboyydigital
```

Untuk channel private dapat menggunakan numeric chat ID:
```env
REQUIRED_CHANNEL_ID=-1001234567890
```

Wajib: Hanya jika fitur join channel digunakan

Catatan:
- Bot sebaiknya menjadi admin channel agar pengecekan member lebih andal.

---

### REQUIRED_CHANNEL_URL
Link tombol Join Channel.

Contoh:
```env
REQUIRED_CHANNEL_URL=https://t.me/maboyydigital
```

Wajib: Jika verifikasi channel digunakan

---

### REQUIRED_CHANNEL_NAME
Nama channel yang ditampilkan di bot.

Contoh:
```env
REQUIRED_CHANNEL_NAME=Maboyy Digital
```

Wajib: Tidak

---

## 3. Database Persisten

### DB_PATH
Lokasi database SQLite aktif.

Untuk Railway Volume:
```env
DB_PATH=/data/shop.db
```

Wajib: Sangat disarankan

Catatan:
- Railway Volume harus dimount ke `/data`.
- Dengan ini database tidak hilang saat redeploy.

Data yang tersimpan antara lain:
- user
- saldo
- ledger
- produk
- variasi
- stok
- order
- voucher
- top up
- pengaturan bot
- QRIS Telegram file_id

---

## 4. Backup Otomatis

### BACKUP_DIR
Lokasi penyimpanan file backup.

Contoh:
```env
BACKUP_DIR=/data/backups
```

Wajib: Ya jika backup otomatis dipakai

---

### BACKUP_INTERVAL_HOURS
Interval backup dalam jam.

Saat ini disarankan:
```env
BACKUP_INTERVAL_HOURS=48
```

Artinya:
- backup otomatis setiap 2 hari

---

### BACKUP_RETENTION
Jumlah maksimal file backup lokal yang disimpan.

Contoh:
```env
BACKUP_RETENTION=20
```

Artinya:
- hanya 20 backup terbaru yang dipertahankan
- backup lama akan dibersihkan otomatis

Backup juga dikirim langsung ke PM owner berdasarkan `ADMIN_ID`.

Tidak ada variable `BACKUP_CHANNEL_ID`.

---

## 5. Reservasi Stok Checkout

### ORDER_RESERVATION_MINUTES
Durasi stok ditahan saat user membuat order QRIS pending.

Contoh:
```env
ORDER_RESERVATION_MINUTES=15
```

Artinya:
- stok direservasi selama 15 menit
- jika belum dibayar sampai habis waktu, order menjadi expired
- stok otomatis dilepas kembali

---

## 6. Stok Otomatis ke Channel

### STOCK_CHANNEL_ID
Channel untuk menampilkan stok terbaru otomatis.

Channel publik:
```env
STOCK_CHANNEL_ID=@maboyydigital
```

Channel private:
```env
STOCK_CHANNEL_ID=-1001234567890
```

Wajib: Hanya jika fitur stok channel digunakan

Catatan:
- Bot harus menjadi admin.
- Bot mengedit satu pesan stok yang sama agar tidak spam.

---

## 7. Payment Gateway / QRIS Otomatis

Bagian ini opsional. Jika belum memakai payment gateway otomatis, biarkan nonaktif.

### SHOPEEPAY_ENABLED
Aktif/nonaktif payment gateway otomatis.

Default:
```env
SHOPEEPAY_ENABLED=false
```

Aktif:
```env
SHOPEEPAY_ENABLED=true
```

---

### SHOPEEPAY_BASE_URL
Base URL API payment gateway.

Contoh:
```env
SHOPEEPAY_BASE_URL=
```

---

### SHOPEEPAY_CLIENT_ID
Client ID dari payment provider.

```env
SHOPEEPAY_CLIENT_ID=
```

---

### SHOPEEPAY_CLIENT_SECRET
Client Secret payment provider.

```env
SHOPEEPAY_CLIENT_SECRET=
```

Rahasia. Jangan upload ke GitHub.

---

### SHOPEEPAY_MERCHANT_ID
Merchant ID.

```env
SHOPEEPAY_MERCHANT_ID=
```

---

### SHOPEEPAY_STORE_ID
Store ID.

```env
SHOPEEPAY_STORE_ID=
```

---

### SHOPEEPAY_TERMINAL_ID
Terminal ID.

```env
SHOPEEPAY_TERMINAL_ID=
```

---

### SHOPEEPAY_PRIVATE_KEY
Private key untuk signature.

```env
SHOPEEPAY_PRIVATE_KEY=
```

Sangat rahasia.

---

### SHOPEEPAY_PUBLIC_KEY
Public key untuk verifikasi callback/signature.

```env
SHOPEEPAY_PUBLIC_KEY=
```

---

### PUBLIC_BASE_URL
Public URL Railway untuk callback payment gateway.

Contoh:
```env
PUBLIC_BASE_URL=https://nama-service.up.railway.app
```

Digunakan untuk endpoint callback pembayaran otomatis.

---

## 8. Rekomendasi Variable Railway Aktif

Jika saat ini hanya menggunakan QRIS manual + backup + channel + stok otomatis:

```env
BOT_TOKEN=
ADMIN_ID=
ADMIN_USERNAME=
PAYMENT_NOTE=QRIS Maboyy Digital

REQUIRED_CHANNEL_ID=
REQUIRED_CHANNEL_URL=
REQUIRED_CHANNEL_NAME=Maboyy Digital

DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
BACKUP_INTERVAL_HOURS=48
BACKUP_RETENTION=20

ORDER_RESERVATION_MINUTES=15

STOCK_CHANNEL_ID=

SHOPEEPAY_ENABLED=false
```

Variable payment gateway lainnya boleh tetap kosong.

---

## 9. Railway Volume

Buat Railway Volume dan mount ke:

```text
/data
```

Variable terkait:

```env
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
```

Tanpa Volume, file lokal service Railway dapat hilang saat redeploy.

---

## 10. Variable yang Sudah Tidak Digunakan

Tidak perlu:

```env
BACKUP_CHANNEL_ID=
UPDATE_CHANNEL_ID=
MABOYY_CONFIG=
```

---

## 11. Keamanan

Jangan pernah upload nilai asli berikut ke GitHub:

```text
BOT_TOKEN
SHOPEEPAY_CLIENT_SECRET
SHOPEEPAY_PRIVATE_KEY
credential payment gateway lainnya
```

Simpan semuanya hanya di Railway Variables.

---

Maboyy Digital
Aplikasi Premium • Since 2020


## Perilaku Backup & Stok Setelah v3.1

### Backup
`BACKUP_INTERVAL_HOURS=48` tidak memicu backup saat bot baru start/redeploy.
Backup otomatis pertama dilakukan setelah interval 48 jam penuh.

### Stok Channel
`STOCK_CHANNEL_ID` tidak akan menerima update hanya karena bot start/redeploy.
Pesan stok hanya berubah jika stok/transaksi benar-benar berubah atau owner melakukan sinkron manual.


## v3.2 — Stok Akun Premium

Tidak ada Railway Variable baru.

Data akun premium disimpan di database persisten `/data/shop.db`, sehingga Railway Volume tetap wajib digunakan.

Pengisian stok dilakukan dari panel owner:

```text
/owner → 📦 Atur Stok → pilih produk → pilih variasi → ➕ Tambah Akun
```


## v3.3 — STOCK_CHANNEL_ID Manual

`STOCK_CHANNEL_ID` tetap digunakan, tetapi bot tidak lagi memperbarui channel secara otomatis.

Update stok channel hanya dilakukan oleh owner:

```text
/owner → 📢 Sinkron Stok Channel
```

Perubahan stok, pembayaran, order, expiry, penambahan akun, atau redeploy tidak akan mengubah pesan stok channel.


## v3.4 — Audit Checkout

Tidak ada Railway Variable baru.

Untuk produk akun premium, stok mengikuti akun yang benar-benar dimasukkan:

```text
/owner → 📦 Atur Stok → pilih produk → pilih variasi → ➕ Tambah Akun
```

Ini mencegah user membeli stok angka yang tidak memiliki data akun untuk dikirim.


## v3.5 — Hapus Produk

Tidak ada Railway Variable baru.

Hapus produk sekarang menggunakan pilihan tombol dan konfirmasi. Produk dinonaktifkan (soft delete), bukan dihapus permanen, agar riwayat transaksi lama tetap aman.


## v3.6 — Recovery & Kontrol Owner

Tidak ada Railway Variable baru.

Fitur baru seluruhnya berada di panel `/owner`:
- 🩺 Cek Sistem
- ♻️ Recovery Order
- 📨 Kirim Ulang Akun
- ❌ Batalkan Order


## v3.7 — Restock Alert User Terverifikasi

Tidak ada Railway Variable baru.

Daftar user terverifikasi disimpan otomatis di database persisten.

Restock Alert otomatis dikirim ke PM user hanya ketika stok sebuah variasi berubah dari `0` menjadi tersedia.

Owner juga dapat mengirim manual dari:

```text
/owner → 📦 Atur Stok → pilih produk → pilih variasi → 📣 Broadcast Restock
```

Update stok channel tetap manual oleh owner.


## v3.8 — Catatan Checkout

Tidak ada Railway Variable baru.

Catatan checkout disimpan langsung di database order pada kolom `note`.


## v3.9 — Tampilan Produk

Tidak ada Railway Variable baru.

Halaman produk sekarang menampilkan nama variasi, harga, dan stok tersedia langsung pada pesan dan tombol variasi.


## v4.0 — Tombol Variasi

Tidak ada Railway Variable baru.

Tombol variasi hanya menampilkan nama variasi dan stok, sedangkan harga tetap ditampilkan pada isi detail produk.


## v4.1 — Nama Tombol Variasi

Tidak ada Railway Variable baru.

Nama tombol variasi disimpan di database. Angka stok pada tombol tetap otomatis mengikuti stok tersedia.


## v4.2 — Menu Bawah Telegram

Tidak ada Railway Variable baru.

Bot menampilkan persistent Reply Keyboard saat `/start` untuk akses cepat ke menu user.


## v4.3 — Quantity & Isi Saldo

Tidak ada Railway Variable baru.

Pemilihan jumlah beli sekarang memakai tombol angka berdasarkan stok tersedia.

Isi saldo memiliki nominal cepat, tambah/kurang, nominal custom, konfirmasi, dan anti double invoice.


## v4.4 — Menu Nomor Produk

Tidak ada Railway Variable baru.

Reply Keyboard Telegram menampilkan nomor 1 sampai jumlah produk aktif (maksimal 25). Menekan nomor langsung membuka produk sesuai urutan List Produk.


## v4.6 — Xoftware Dibatalkan

Variable berikut tidak digunakan dan boleh dihapus dari Railway jika sebelumnya sempat ditambahkan:

```env
XOFTWARE_ENABLED
XOFTWARE_BASE_URL
XOFTWARE_API_KEY
XOFTWARE_MERCHANT_ID
XOFTWARE_WEBHOOK_SECRET
```

`PUBLIC_BASE_URL` tetap boleh dipertahankan jika digunakan oleh integrasi payment gateway lama.

Bot kembali menggunakan konfigurasi sebelum integrasi Xoftware.


## v4.7 — Professional Operations Pack

Tidak ada Railway Variable baru.

Pengaturan baru disimpan di SQLite `settings`:
- `low_stock_threshold` default 5
- `fraud_pending_limit` default 3
- `fraud_cooldown_seconds` default 8
- `loyalty_silver` default 250000
- `loyalty_gold` default 750000
- `loyalty_vip` default 2000000

Semua migrasi database dilakukan otomatis ketika bot start.


## v4.8 — Button Based Owner Settings

Tidak ada Railway Variable baru.

Menu owner untuk voucher, top up verification/rejection, dan anti-fraud sekarang menggunakan tombol pilihan agar owner tidak perlu mengetik ID atau format dengan pemisah `|`.


## v4.9 — Stability, Operations & Growth Pack

Tidak ada Railway Variable baru.

Pengaturan baru tersimpan di SQLite `settings`:
- `maintenance_mode` default `0`
- `cashback_percent` default `0`
- `daily_report_enabled` default `1`
- `daily_report_hour` default `20`

Laporan harian dihitung dengan zona waktu Asia/Jakarta.


## v5.0 — Navigation Reliability Fix

Tidak ada Railway Variable baru.

Update ini hanya memperbaiki routing callback/navigation dan kompatibilitas tombol lama.


## v5.1 — Owner Menu Ringkas

Tidak ada Railway Variable baru.
Perubahan hanya pada pengelompokan menu `/owner`; fungsi lama tetap dipertahankan.


## v5.2 — Restock Notification Fix

Tidak ada Railway Variable baru.
Restock subscription sekarang bersifat toggle dan owner menerima PM status subscription serta summary pengiriman.


## v5.3 — Restock Unsubscribe Silent

Tidak ada Railway Variable baru.
PM owner hanya dikirim saat subscribe ON, bukan saat subscribe OFF.


## v5.4 — Payment Flow Hardening

Tidak ada Railway Variable baru.
Database migration otomatis menambahkan payment audit/verification metadata.


## v5.5 — Transfer Rekening untuk Isi Saldo

Tidak ada Railway Variable baru.
Data rekening disimpan di SQLite settings:
- bank_name
- bank_account
- bank_holder


## v5.6 — Mandatory Global Unique Payment Code

Tidak ada Railway Variable baru.
Kode unik sekarang wajib dan dialokasikan berurutan melalui database.
Setting `unique_code_enabled` selalu dipaksa `1`.


## v5.7 — Transfer Rekening untuk Pembelian Produk

Tidak ada Railway Variable baru.
Data rekening memakai SQLite settings yang sudah tersedia dari v5.5.


## v5.8 — Stability Audit

Tidak ada Railway Variable baru. Migration otomatis menambahkan `topups.expires_at`.


## v5.9 — Invoice Expiry & Auto Cleanup

Tidak ada Railway Variable baru.

Settings SQLite:
- invoice_history_retention_days = 7
- expired_invoice_hide_minutes = 60

Paid/completed transaction records are preserved automatically.


## v6.0 — QRIS Upload Fix

Tidak ada Railway Variable baru. QRIS tetap disimpan melalui Telegram file_id.


## v6.1 — Loading Animation

Tidak ada Railway Variable baru.


## v6.2 — Stability & Recovery Pack

Tidak ada Railway Variable baru.

Settings SQLite baru:
- safe_mode = 0
- system_error_pm_enabled = 1
- auto_repair_inventory = 1
- auto_recovery_enabled = 1


## v6.3 — Owner UX & Back Navigation Fix

Tidak ada Railway Variable baru.


## v6.4 — Free-Form Account Input

Tidak ada Railway Variable baru.


## v6.5 — Full Button Reliability & Alert Dedup

Tidak ada Railway Variable baru.


## v6.6 — Payment Proof Review

Tidak ada Railway Variable baru. Bukti pembayaran disimpan sebagai Telegram file_id.


## v6.7 — Checkout Note Fix

Tidak ada Railway Variable baru.


## v6.8 — Duplicate Cleanup & Menu Simplification

Tidak ada Railway Variable baru.


## v6.9 — Invoice Gambar Profesional

Tidak ada Railway Variable baru.


## v7.0 — Invoice Image Only

Tidak ada Railway Variable baru.


## v7.1 — README Ringkas

Tidak ada Railway Variable baru.


## v7.2 — Owner Access Hardening

Tidak ada Railway Variable baru.


## v7.3 — Command Cleanup

Command bot tetap hanya `/start`, `/owner`, `/ping`. Tidak ada Railway Variable baru.


## v7.4 — Pillow Crash Fix

Tidak ada Railway Variable baru. Pastikan `requirements.txt` terbaru ikut di-upload dan Railway diredeploy.


## v7.5 — Simple Selection Menu

Tidak ada Railway Variable baru.


## v7.6 — QRIS Upload Reliability

Tidak ada Railway Variable baru.


## v7.7 — Payment Proof PM Fix

Tidak ada Railway Variable baru. Pastikan owner pernah membuka/start bot agar bot dapat mengirim PM ke owner.


## v7.8 — Channel Verification Fix

Tidak ada Railway Variable baru. REQUIRED_CHANNEL_ID harus mengarah ke channel yang sama dengan tombol Join Channel.


## v7.9 — Pre-Launch Stability

Tidak ada Railway Variable baru. Gunakan `/owner → ⚙️ Sistem → 🚦 Launch Readiness` sebelum membuka bot ke user.


## v8.0 — Readiness via Ping

Gunakan `/ping` untuk pengecekan kesiapan bot. Tidak ada Railway Variable baru.


## v8.1 — Required Channel Admin Check

Agar verifikasi membership user di channel dapat bekerja konsisten, bot harus ditambahkan sebagai admin pada REQUIRED_CHANNEL_ID. Tidak ada Railway Variable baru.


## v8.2 — Ping Owner Only

`/ping` hanya dapat digunakan owner. Tidak ada Railway Variable baru.


## v8.3 — Owner System Menu Fix

Tidak ada Railway Variable baru.


## v8.4 — Add Variant Wizard

Tidak ada Railway Variable baru.


## v8.5 — Variant Merge

Menu Tambah Variasi digabung ke Tambah Produk. Tidak ada Railway Variable baru.


## v8.6 — Variant Price Input Fix

Tidak ada Railway Variable baru.


## v8.7 — Detailed Ping

`/ping` menampilkan waktu WIB, tanggal lengkap, waktu mulai bot, dan runtime detail. Tidak ada Railway Variable baru.


## v8.8 — Compact Ping Info

Tanggal dan jam sekarang digabung ke Informasi Bot. Tidak ada Railway Variable baru.


## v8.9 — Ping Cleanup

Bagian Mulai aktif dihapus dari `/ping`. Tidak ada Railway Variable baru.


## v9.0 — Safe Data Cleanup

Menu Sistem owner memiliki fitur Hapus Data dengan preview dan konfirmasi. Data paid/completed tidak dihapus. Tidak ada Railway Variable baru.


## v9.1 — Pending Order Cleanup

Menu Hapus Data sekarang memiliki opsi Pesanan Pending. Hanya order belum bayar yang dapat dihapus dan reservasi stok dilepas terlebih dahulu. Tidak ada Railway Variable baru.


## v9.2 — System Stability Audit

Memperbaiki query cleanup order dari `expires_at` menjadi `reserved_until` dan menambah schema check pada Diagnostik. Tidak ada Railway Variable baru.


## v9.3 — Product Wizard Database Fix

Menambahkan migration `products.created_at` dan memperkuat handler harga pada Tambah Produk. Tidak ada Railway Variable baru.


## v9.4 — Keyboard Refresh

Ditambahkan tombol `🔄 Perbarui Keyboard` untuk menghapus keyboard lama dan mengirim ulang keyboard terbaru di Android/iOS. Tidak ada Railway Variable baru.


## v9.5 — Owner System Callback Routing Fix

Handler callback catch-all dipindahkan ke posisi terakhir agar tidak menelan callback Sistem owner yang valid. Tidak ada Railway Variable baru.


## v9.6 — Full Stability Audit

Audit callback, OwnerState, QRIS routing, wizard, payment, inventory, dan fallback. Tidak ada Railway Variable baru.


## v9.7 — Custom Price State Fix

Handler harga custom dipastikan lebih dulu dari generic fallback dan ditambahkan recovery jika FSM state hilang. Tidak ada Railway Variable baru.


## v9.8 — Free Variant Pricing

Atur Harga Varian sekarang menerima nominal bebas setelah memilih produk dan varian. Tidak ada Railway Variable baru.


## v9.9 — Recovery Status Clarification

Startup Recovery sekarang membedakan order unpaid pending dan order paid yang belum terkirim. Data SQLite tetap persisten selama Railway Volume `/data` terpasang. Tidak ada Railway Variable baru.


## v10.0 — Product Menu Stability

Seluruh menu Produk & Stok diperkuat. Produk Populer/Flash Sale sekarang toggle tombol. Tidak ada Railway Variable baru.


## v10.1 — Auto Recovery Layer

Self-healing aman ditambahkan untuk order recovery, inventory repair, topup processing reset, proof-session cleanup, DB integrity check, dan Safe Mode fallback. Tidak ada Railway Variable baru.


## v10.2 — Persistent Price Input

Sesi input Harga Custom owner sekarang disimpan di SQLite sehingga tidak hilang ketika FSM terganggu atau bot redeploy. Tidak ada Railway Variable baru.


## v10.3 — Keyboard Helper Audit

Memperbaiki helper Hapus Produk dan Atur Stok yang belum didefinisikan, serta audit semua helper keyboard. Tidak ada Railway Variable baru.


## v10.4 — Stability Audit

Memperbaiki helper `owner_stock_variant_actions` yang hilang dan melakukan audit direct function calls serta helper keyboard. Tidak ada Railway Variable baru.


## v10.5 — Error Analytics

Structured error logging menyimpan update ID, event, callback, user, exception type dan traceback ringkas ke system_errors. Diagnostik menampilkan 5 error terakhir. Tidak ada Railway Variable baru.


## v10.6 — Production State Fix

FSM sekarang menggunakan SQLite persisten di DB_PATH yang sama. `drop_pending_updates` diubah menjadi `False` agar update Telegram yang antre tidak dibuang saat restart/redeploy. Tidak ada Railway Variable baru.


## v10.7 — Production Hardening

Event isolation, polling backoff/concurrency limit, SQLite WAL+busy_timeout, dan pemisahan Telegram transient errors diterapkan. Tidak ada Railway Variable baru.


## v10.8 — Button Reliability Pack

`allowed_updates` eksplisit menerima callback_query, semua callback handler diaudit untuk acknowledgement, dan Callback Trace Middleware ditambahkan. Tidak ada Railway Variable baru.


## v10.9 — Price Routing Fix

Broad F.text recovery handlers dihapus dan diganti custom filter yang hanya aktif pada persisted owner price session. Smoke test SQLite harga 2500 berhasil. Tidak ada Railway Variable baru.


## v11.0 — Runtime NameError Audit

Memperbaiki missing `re`, `JAKARTA_TZ`, `main_menu`, dan `expiry_text`, serta membuang dead startup recovery code. Symbol-table audit sekarang wajib 0 unresolved global symbol sebelum ZIP rilis. Tidak ada Railway Variable baru.


## v11.1 — Pending Order / Delete Product Fix

Produk boleh soft-delete walau ada pending order. Unpaid pending dibatalkan dan reservation dilepas; paid pending dipertahankan. Menu Order Pending ditambahkan untuk restock/fulfillment. Tidak ada Railway Variable baru.


## v11.2 — Verifikasi Pembayaran

Menu Order & Pembayaran sekarang punya verifikasi pembayaran terpusat: lihat bukti, confirm, reject, pending. Confirm memakai `mark_order_paid()` existing flow. Tidak ada Railway Variable baru.


## v11.3 — Paid Pending Purge

Paid-undelivered orders dapat dipurge dari Hapus Data dan otomatis dibersihkan saat Hapus Produk. Allocated inventory dikembalikan ke available, reservation dilepas, dan data orphan tetap terdeteksi langsung dari orders. Tidak ada Railway Variable baru.


## v11.4 — Demo & Report Cleanup

Menambahkan /demo owner untuk seed/clear data uji pembayaran dan topup. Laporan harian mulai disimpan ke daily_report_history. Hapus Data diperluas untuk riwayat laporan, log operasional, dan data demo. Tidak ada Railway Variable baru.


## v11.5 — Pure Demo Simulation

/demo sekarang sepenuhnya simulasi. Tidak membuat produk/order/topup/stok/saldo/transaksi asli dan tidak mengubah produk di /start. Hanya session navigasi demo ringan yang disimpan. Tidak ada Railway Variable baru.


## v11.6 — Demo Isolation Lock

Demo diperketat dengan namespace userdemo:* dan safety-net. AST audit memastikan handler demo tidak memanggil DB/fulfillment/payment/topup/inventory produksi dan tidak membuat callback menuju flow toko asli. /start juga diaudit bebas referensi demo. Tidak ada Railway Variable baru.


## v11.7 — Runtime Import Guard

Memastikan import re tersedia, parser memakai local fallback import, dan startup dependency self-test dijalankan sebelum polling. Tidak ada Railway Variable baru.


## v12.0 — Major Hardening

Fulfillment resume-safe, stale-topup guard, single-instance conflict protection, graceful shutdown, QRIS transient cleanup, unified payment review state, database health/repair, owner audit log, demo isolation self-test, statistik produk, serta pencarian order/user/produk. Tidak ada Railway Variable baru.


## v12.1 — Deployment Fingerprint

Menggunakan Railway-provided variables (`RAILWAY_DEPLOYMENT_ID`, `RAILWAY_REPLICA_ID`, `RAILWAY_GIT_COMMIT_SHA`, `RAILWAY_ENVIRONMENT_NAME`) untuk menandai versi runtime pada log, /ping, /health, dan Diagnostik. Tidak ada Railway Variable manual baru.


## v12.2 — Railway Entrypoint Fix

Menambahkan root `main.py` launcher. Ini penting karena Railway/Railpack dapat otomatis memilih `main.py` untuk aplikasi Python. Launcher memastikan `bot.py` yang diimpor harus versi 12.2 dan parser harga harus lolos self-test sebelum polling. Upload `main.py` dan `bot.py` bersama ke root repository. Tidak ada Railway Variable baru.


## v12.3 — Startup Demo Constant Hotfix

Memperbaiki konstanta demo self-reference yang menyebabkan crash saat `import bot`. Tidak ada Railway Variable baru. Upload `main.py` dan `bot.py` v12.3 bersama.


## v12.4 — Payment Confirmation History

Setelah owner mengonfirmasi pembayaran, bot memberikan feedback final dan order masuk ke `History Sukses` berbasis payment_status=paid. Status fulfillment tetap dibedakan antara delivered dan menunggu akun. Tidak ada Railway Variable baru.


## v12.5 — Checkout Terms

Menambahkan syarat singkat akun Sharing/Private ke layar checkout dan invoice pembayaran. Tidak ada perubahan pada alur transaksi atau Railway Variable.


## v12.6 — Duplicate Stock

Mode sharing dapat menduplikasi satu akun menjadi 2/5/10/20/50/custom hingga 500 stok dalam satu kali input. Mode private/single tetap menolak duplikat. Tidak ada Railway Variable baru.


## v12.7 — Sharing Qty Guard

Varian yang memakai duplicate stock otomatis menjadi sharing dan maksimal Qty 1 pada seluruh checkout. Legacy duplicated inventory otomatis ditandai sharing. Tidak ada Railway Variable baru.


## v12.8 — Rating & Ulasan

Menambahkan prompt rating otomatis setelah fulfillment delivered, ulasan teks hingga 500 karakter, fallback rating dari Pesanan Saya, statistik owner, dan notifikasi ulasan. Review tidak memengaruhi keberhasilan fulfillment. Tidak ada Railway Variable baru.


## v12.9 — Rating Toko

Rating sekarang dihitung untuk Maboyy Digital secara keseluruhan, bukan per produk. Review menyimpan snapshot nama produk/varian hanya sebagai konteks transaksi dan tetap bertahan meskipun produk dihapus/nonaktifkan. Tidak ada Railway Variable baru.


## v13.0 — Compact Ping

Tampilan /ping diringkas menjadi status, versi, database, deployment singkat, dan commit. Pemeriksaan teknis tetap berjalan secara internal. Tidak ada Railway Variable baru.


## v13.1 — Compact Ping + Tanggal

Tanggal dan waktu WIB dikembalikan ke /ping tanpa mengembalikan detail teknis panjang. Tidak ada Railway Variable baru.


## v13.2 — Backup Project

Menambahkan tombol manual `📦 Backup Project` pada menu Sistem. ZIP berisi 6 file project yang dideploy + snapshot `shop.db`. `.env`/secret Railway sengaja tidak disertakan. Backup database otomatis 48 jam tetap aktif. Tidak ada Railway Variable baru.


## v13.3 — Stok di List Produk
- Menu list produk user sekarang menampilkan stok total per produk.
- Tombol pilihan produk juga menampilkan jumlah stok saat ini.


## v13.4 — Indikator Stok
- Indikator stok user: 🔴 0, 🟡 1–3, 🟢 4+.
- Memperbaiki version guard launcher agar sesuai v13.4.
- Tidak ada Railway Variable baru.


## v13.5 — Stok Ringkas

Indikator warna stok dihapus. List Produk tetap menampilkan jumlah stok per produk dan tombol produk tetap menampilkan angka stok. Tidak ada Railway Variable baru.


## v13.6 — Contoh Catatan Pesanan
- Hanya perubahan teks contoh catatan checkout.
- Tidak ada Railway Variable baru.


## v13.7 — Alur Verifikasi Bukti Pembayaran
- Tidak ada Railway Variable baru.
- Perubahan hanya pada routing/pesan verifikasi bukti dan filter menu verifikasi.


## v13.8 — User Flow & Reliability Upgrade
- Detail Pesanan Saya + cek status + cancel unpaid.
- Notifikasi status bukti/pembayaran.
- Dashboard owner diperluas.
- Rating toko publik.
- Metadata backup project + info backup terakhir.
- Conservative cleanup 6 jam untuk support-data lama.
- Startup self-test owner report.
- Tidak ada Railway Variable baru.


## v13.9 — Repair Semua Menu Hapus Data
- Semua preview/confirm cleanup disinkronkan.
- Tidak ada Railway Variable baru.


## v14.0 — Owner Free Claim
- Menambahkan pengambilan stok owner tanpa saldo untuk pembeli di luar bot.
- Metode order: `OWNER_FREE`, payment_total Rp0.
- Menggunakan fulfillment/recovery order yang sama dengan pembelian normal.
- Tidak ada Railway Variable baru.


## v14.1 — Kode Unik Maksimal Rp500
- Rentang kode unik dikunci ke 1–500.
- Setting lama otomatis dimigrasikan ke maksimum 500.
- Tidak ada Railway Variable baru.


## v14.2 — Kode Unik Rp200–Rp500
- unique_code_min otomatis menjadi 200.
- unique_code_max tetap 500.
- Tidak ada Railway Variable baru.


## v14.3 — Bulk Stok Private/Unique
- Tidak ada Railway Variable baru.
- Preset jumlah: +5 / +10 / +20 / +50.
- Custom: 2–500.
- Akun dimasukkan satu per satu dan wajib berbeda.
- Staging disimpan di database sebelum finalisasi inventory.


## v14.4 — Terjual Persisten
- Tidak ada Railway Variable baru.
- `Terjual` direbuild dari order history saat startup.
- Railway Volume `/data` harus tetap aktif agar histori tidak hilang saat redeploy.


## v15.0 — Major Reliability & Owner Tools
- Tidak ada Railway Variable baru.
- Menambah riwayat akun terjual, dashboard stok, claim log, payment reconciliation, customer profile, dan audit owner.


## v15.1
- Tidak ada Railway Variable baru.
- Smart Alert menyimpan signature di SQLite settings.
- Refund masuk ke Saldo Kamu menggunakan wallet ledger.
- Rekening opsional tidak lagi membuat startup check gagal.


## v15.2 — Customer Profile Hotfix
- Tidak ada Railway Variable baru.
- Wajib upload semua 6 file release bersama agar source version sinkron.


## v15.3 — /ping IPv4 / IPv6
- Tidak ada Railway Variable baru.
- Public IPv4 dan IPv6 dideteksi ketika `/ping` dipanggil.


## v15.4 — Owner UI Simplification
- Tidak ada Railway Variable baru.
- Hanya restrukturisasi menu/callback; database path dan konfigurasi Railway tetap sama.


## v15.5 — Navigation Fix
- Tidak ada Railway Variable baru.
- Parent callback tombol Kembali disinkronkan dengan menu v15.4.


## v15.6 — Atur Harga UI
- Tidak ada Railway Variable baru.
- Hanya memindahkan tombol Atur Harga ke menu utama Produk & Stok.


## v15.7 — Buyer Transaction Menu
- Tidak ada Railway Variable baru.
- Perubahan fokus pada UI/callback checkout pembeli; DB dan payment credentials tetap sama.


## v15.8 — Transaction Cleanup
- Tidak ada Railway Variable baru.
- Fix literal newline dan penyederhanaan UI transaksi pembeli.


## v15.9 — Start Welcome Fix
- Tidak ada Railway Variable baru.
- `/start` hanya mengirim satu pesan sambutan.


## v16.0 — Transaction & Stock Reliability
- Tidak ada Railway Variable baru.
- Tidak ada perubahan secret atau payment credential.


## v16.1 — Payment Flow Hardening
- Tidak ada Railway Variable baru.
- Tidak ada perubahan secret/payment credential.


## v16.2 — Stability Hardening (base v16.1)
- Tidak ada Railway Variable baru.
- Tidak ada perubahan alur pembayaran user.


## v16.3 — One Proof Per Invoice
- Tidak ada Railway Variable baru.
- Satu invoice maksimal satu bukti pembayaran.


## v16.4 — Payment FSM Navigation Fix
- Tidak ada Railway Variable baru.
- Tambah tombol Menu Utama dan perbaikan state proof upload.


## v16.5 — Payment Recovery Fix
- Tidak ada Railway Variable baru.
- Perbaikan fallback bukti pembayaran dan recovery owner.


## v16.6 — Order Cleanup + Smart Alert Control
- Tidak ada Railway Variable baru.
- Smart Alert default OFF dan dikontrol dari menu owner.
- Pesanan final/rejected disembunyikan dari UI user setelah 24 jam.


## v16.7 — Production Reliability
- Tidak ada Railway Variable baru.
- Penambahan schema migration record, trace transaksi, dan persistent rate limiter.


## v16.8 — Copy-Friendly Bank Account
- Tidak ada Railway Variable baru.
- Nomor rekening ditampilkan dalam blok copy-friendly.


## v16.9 — Compact Riwayat
- Tidak ada Railway Variable baru.
- Pesanan Saya diganti UI Riwayat yang lebih ringkas.


## v16.10 — Owner Proof Action Fix
- Tidak ada Railway Variable baru.
- Perbaikan respons tombol reject/final dan Menu Awal owner.


## v16.11 — Compact Variant Price Stock
- Tidak ada Railway Variable baru.
- Tampilan varian/harga/stok dibuat satu baris per varian.


## v16.12 — Historical Payment Auto-Repair
- Tidak ada Railway Variable baru.
- Recovery startup menormalisasi status payment/proof historis sebelum Self-Test.


## v16.13 — Native Copy Bank Account
- Tidak ada Railway Variable baru.
- Tombol Telegram native copy_text digunakan untuk menyalin nomor rekening saja.


## v16.14 — Payment Method Consistency
- Tidak ada Railway Variable baru.
- Validasi metode pembayaran dilakukan sebelum commit order.


## v16.15 — Remove Dead Quantity Buttons
- Tidak ada Railway Variable baru.
- Tombol qty tanpa aksi/noop dihapus dari UI user.


## v16.16 — Compact Product Catalog
- Tidak ada Railway Variable baru.
- Tampilan List Produk dibuat satu blok nomor + nama + stok.


## v16.17 — Simple Bulk Stock
- Tidak ada Railway Variable baru.
- Tambah Stok Banyak menerima banyak akun dalam satu pesan; 1 baris = 1 stok.
- Duplikat Akun Sharing dihapus dari menu owner.


## v16.18 — Unified Account & Stock
- Tidak ada Railway Variable baru.
- Inventory user-facing owner disatukan: 1 akun = 1 stok.


## v16.19 — Free-Text Account Input
- Tidak ada Railway Variable baru.
- Input akun: 1 pesan teks bebas = 1 akun = 1 stok.


## v16.20 — Batch Private + Sharing Duplicate
- Tidak ada Railway Variable baru.
- Private batch: pisahkan akun dengan `---`.
- Duplikat Akun Sharing aktif kembali.


## v16.21 — Free-Text Sequential Stock
- Tidak ada Railway Variable baru.
- Private: 1 pesan teks bebas = 1 akun = 1 stok.
- Session tetap aktif agar owner dapat mengirim akun berikutnya tanpa membuka menu ulang.
- Duplikat Akun Sharing tetap tersedia.


## v16.22 — Target Quantity Account Input
- Tidak ada Railway Variable baru.
- Owner memilih target 1/2/5/10/20/50 atau Custom.
- Setiap pesan teks bebas = 1 akun = 1 stok; progress otomatis sampai target.
- Duplikat Akun Sharing tetap tersedia.


## v16.23 — Product Catalog Pagination
- Tidak ada Railway Variable baru.
- Tombol produk dan Cari publik dihapus dari List Produk.
- Pagination katalog 5 produk per halaman ditambahkan.


## v16.24 — Pre-Order Fulfillment
- Tidak ada Railway Variable baru.
- Pre-Order menggunakan schema database baru otomatis saat startup.


## v16.25 — User Complaint
- Tidak ada Railway Variable baru.
- Komplain user diteruskan otomatis ke PM owner.


## v16.26 — Inventory Hardening
- Tidak ada Railway Variable baru.
- Schema database naik ke 171 dan migrasi berjalan otomatis saat startup.
- Private inventory sekarang memakai fingerprint + DB unique guard.


## v16.27 — Famhead + Login Proof
- Tidak ada Railway Variable baru.
- Schema naik ke 172; migrasi otomatis saat startup.
- Produk Famhead menggunakan Gmail user dan alur undangan Family.
- Bukti login disimpan di SQLite + file_id Telegram.


## v16.28 — WIB + Pagination Order
- Tidak ada Railway Variable baru.
- Schema tetap 172.
- Semua waktu UI dikonversi ke Asia/Jakarta (WIB).
- Owner Pesanan Terbaru: 4 order per halaman dengan tombol kiri/kanan.


## v16.29 — User History + Rating Entry
- Tidak ada Railway Variable baru.
- Schema tetap 172.
- Riwayat user 4 transaksi per halaman dengan kiri/kanan.
- Rating yang belum diberikan bisa dibuka dari Riwayat/detail order.
- Rating Toko & Ulasan dipindahkan dari Menu Utama ke tampilan /start.


## v16.30 — /start Button Cleanup
- Tidak ada Railway Variable baru.
- Schema tetap 172.
- Tombol /start disederhanakan menjadi `⭐ Rating Toko` dan `🛍️ Buka Menu Utama`.


## v16.31 — Backup Project Hardening
- Tidak ada Railway Variable baru.
- Schema tetap 172.
- `.env.example`/docs tidak lagi wajib ada di container Railway agar Backup Project berhasil.
- `.env` asli tetap tidak pernah dibackup.


## v16.32 — Timed Flash Sale
- Tidak ada Railway Variable baru.
- Schema naik ke 173.
- Timer Flash Sale disimpan di SQLite dan aman terhadap restart/redeploy.


## v16.33 — Owner Tools Provider (OPSIONAL)
```text
TOOLS_PROVIDER_ENABLED=false
TOOLS_PROVIDER_NAME=Authorized Provider
TOOLS_PROVIDER_STATUS_URL=
TOOLS_PROVIDER_PROVISION_URL=
TOOLS_PROVIDER_API_KEY=
TOOLS_PROVIDER_TIMEOUT_SECONDS=12
```
Gunakan hanya endpoint/API provider resmi atau yang memang mengizinkan provisioning.


## v16.34 — `/tools` hardening

Tambahan variable opsional:

```text
TOOLS_PROVIDER_AUTH_MODE=bearer
TOOLS_PROVIDER_MAX_RETRIES=1
TOOLS_PROVIDER_REQUEST_COOLDOWN_SECONDS=600
TOOLS_PROVIDER_MAX_RESPONSE_CHARS=2000
```

`TOOLS_PROVIDER_AUTH_MODE` mendukung `bearer` atau `x-api-key`.

API key yang pernah dibagikan di chat harus dianggap terekspos dan di-rotate.
Jangan menaruh API key langsung di `bot.py`.

Schema tetap 174.


## v16.35 — Statistik & Kuota Tools

Tambahkan:

```text
TOOLS_PROVIDER_HOURLY_LIMIT=15
TOOLS_PROVIDER_REQUESTS_PER_ACCOUNT=3
```

- `HOURLY_LIMIT`: batas request API per jam.
- `REQUESTS_PER_ACCOUNT`: estimasi konsumsi request untuk satu proses akun.
- Reset counter lokal mengikuti awal jam WIB.
- Schema tetap 174.


## v16.36 — Magic Link & Verify

Tambahkan:

```text
TOOLS_PROVIDER_MAGICLINK_URL=
TOOLS_PROVIDER_VERIFY_URL=
```

Isi dengan endpoint provider yang memang kamu berhak gunakan.

Flow Premium otomatis tidak disambungkan.
Schema tetap 174.


## v16.37 — Railway Variables untuk `/tools`

Gunakan nilai berikut di Railway:

```text
TOOLS_PROVIDER_ENABLED=true
TOOLS_PROVIDER_NAME=Alight Tools
TOOLS_PROVIDER_AUTH_MODE=x-api-key
TOOLS_PROVIDER_MAGICLINK_URL=https://alightfree.my.id/api/v1/send-magiclink
TOOLS_PROVIDER_VERIFY_URL=https://alightfree.my.id/api/v1/verify-account
TOOLS_PROVIDER_TIMEOUT_SECONDS=12
TOOLS_PROVIDER_MAX_RETRIES=1
TOOLS_PROVIDER_REQUEST_COOLDOWN_SECONDS=240
TOOLS_PROVIDER_MAX_RESPONSE_CHARS=2000
TOOLS_PROVIDER_HOURLY_LIMIT=15
TOOLS_PROVIDER_REQUESTS_PER_ACCOUNT=3
```

Catatan:
- `TOOLS_PROVIDER_API_KEY` tidak ditulis ulang di file ini karena sudah disimpan sebagai Railway Secret.
- `TOOLS_PROVIDER_STATUS_URL` tidak digunakan.
- `TOOLS_PROVIDER_PROVISION_URL` tidak digunakan.
- Jangan hapus variable lama bot yang sudah ada di Railway.


## v16.38 — Fix readiness `/tools`

Status READY sekarang hanya membutuhkan:

```text
TOOLS_PROVIDER_ENABLED=true
TOOLS_PROVIDER_API_KEY=<tersimpan sebagai Railway Secret>
TOOLS_PROVIDER_MAGICLINK_URL=https://alightfree.my.id/api/v1/send-magiclink
TOOLS_PROVIDER_VERIFY_URL=https://alightfree.my.id/api/v1/verify-account
```

`TOOLS_PROVIDER_STATUS_URL` dan `TOOLS_PROVIDER_PROVISION_URL` tidak lagi digunakan
untuk menentukan kesiapan `/tools`.


## v16.39 — Nama Alur `/tools`

Nama yang tampil di Telegram disederhanakan:

```text
📧 Kirim Link Verifikasi
✅ Verifikasi Akun
```

Variable internal tetap sama:

```text
TOOLS_PROVIDER_MAGICLINK_URL=https://alightfree.my.id/api/v1/send-magiclink
TOOLS_PROVIDER_VERIFY_URL=https://alightfree.my.id/api/v1/verify-account
```

Tidak perlu mengganti nama variable Railway yang sudah ada.


## v16.40 — Advanced `/tools`

Tidak ada Railway Variable baru.

Schema:
```text
SCHEMA_VERSION=175
```

Tambahan internal:
- `tool_activity_logs`
- pagination riwayat tools
- recovery step terakhir
- diagnostik provider/config


## v16.41 — Advanced `/tools`

Tambahkan:

```text
TOOLS_SESSION_EXPIRY_MINUTES=15
TOOLS_EMAIL_LOCK_SECONDS=300
TOOLS_PROVIDER_STATUS_CACHE_SECONDS=60
```

Tidak ada notifikasi owner otomatis.
Tidak ada export riwayat.

Schema:
```text
SCHEMA_VERSION=176
```


## v16.42 — Secure idToken Capture

Tidak ada Railway Variable baru.

Setelah `verify-account` berhasil, bot mencoba mengambil `idToken` dari response.
Token hanya disimpan sementara di session owner dan tidak dipersistenkan ke database/log.

Schema tetap:
```text
SCHEMA_VERSION=176
```


## v16.43 — Email Target & Final Result

Tidak ada Railway Variable baru.

Flow:
```text
Email Target
→ Kirim Link Verifikasi
→ Verifikasi Akun
→ idToken terdeteksi sementara
→ Hasil Final
```

Schema tetap:
```text
SCHEMA_VERSION=176
```


## v16.44 — Pro License Stage

Tidak ada Railway Variable baru.

Flow:
```text
Email Target
→ Kirim Link Verifikasi
→ Verifikasi Akun
→ idToken terdeteksi
→ Tahap Lisensi Pro
→ Hasil Final
```

Status Premium/Pro hanya ditampilkan aktif jika provider mengembalikan status eksplisit.

Schema tetap:
```text
SCHEMA_VERSION=176
```


## v16.45 — Compact `/tools`

Tidak ada Railway Variable baru.
Perubahan hanya pada UI dan pengelompokan menu `/tools`.
Schema tetap `176`.


## v16.46 — Session Persistence Fix

Tidak ada Railway Variable baru.

Fix:
- `/tools` tidak lagi menghapus session;
- `⬅️ Owner Tools` tidak lagi menghapus session;
- Email Target, verify result, idToken sementara, dan final result dipertahankan;
- reset manual tersedia melalui `🧹 Reset Session`.

Schema tetap `176`.


## v16.47 — Provider-Only Final Result

Tidak ada Railway Variable baru.

Hasil akhir `/tools` sekarang hanya memakai hasil dari provider:

```text
Email Target
→ Kirim Link
→ Verifikasi Provider
→ baca status lisensi dari response provider
→ Hasil Provider
```

Schema tetap `176`.


## v16.48 — Auto Provider Orchestration

Tambahkan:
```text
TOOLS_PROVIDER_POLL_ATTEMPTS=4
TOOLS_PROVIDER_POLL_INTERVAL_SECONDS=3
TOOLS_PROVIDER_TEMP_RETRIES=2
```

Jika provider memiliki `TOOLS_PROVIDER_STATUS_URL`, polling status berjalan otomatis.
Jika tidak, flow tetap selesai memakai response verify/provider yang tersedia.

Schema: `177`.


## v16.49 — Apply Premium Provider Result

Tidak ada Railway Variable baru.

`/tools` sekarang dapat membaca dan menampilkan hasil Apply Premium bila response provider
memuat status tersebut.

Contoh:
```text
🚀 Apply Premium Provider: ✅ BERHASIL
🔎 Apply Ref: ...
🚀 Apply Result: ...
```

Schema tetap `177`.



## v16.50 — Fokus Apply Premium Provider

Tidak ada Railway Variable baru.

Flow `/tools`:
```text
Kirim Link
→ Verifikasi Provider
→ Apply Premium
→ Hasil Provider
```

Tampilan `Lisensi Pro Provider` dihapus.
Schema tetap `177`.


## v16.51 — Apply Premium Status URL

Tambahkan Railway Variable:

```text
TOOLS_PROVIDER_APPLY_STATUS_URL=
```

Gunakan endpoint provider yang hanya membaca status/hasil Apply Premium, misalnya endpoint
dengan path `status`, `result`, `history`, `lookup`, atau `check`.

Endpoint action seperti `/api/v1/apply-premium` tidak digunakan sebagai status URL.

Schema tetap `177`.


## v16.52 — Aksi Apply Premium, Riwayat, dan Stabilitas Provider

Revisi ini hanya mengembangkan `/tools`. Command lain serta pembacaan variable umum tetap
menggunakan implementasi v16.51. Perubahan SQLite/FSM hanya menangani data provider tools.

Variable baru wajib untuk flow apply:

```text
TOOLS_PROVIDER_APPLY_URL=https://alightfree.my.id/api/v1/apply-premium
```

Konfigurasi lengkap provider yang ditunjukkan pada contoh:

```text
TOOLS_PROVIDER_ENABLED=true
TOOLS_PROVIDER_AUTH_MODE=x-api-key
TOOLS_PROVIDER_MAGICLINK_URL=https://alightfree.my.id/api/v1/send-magiclink
TOOLS_PROVIDER_VERIFY_URL=https://alightfree.my.id/api/v1/verify-account
TOOLS_PROVIDER_APPLY_URL=https://alightfree.my.id/api/v1/apply-premium
TOOLS_PROVIDER_APPLY_STATUS_URL=
```

`TOOLS_PROVIDER_API_KEY` tetap Railway Secret; tidak ditanam di source atau `.env.example`.
Apply memakai POST JSON `email` + `idToken` dari respons Verify Account untuk email yang sama.
Nama endpoint ini berasal dari konfigurasi/contoh provider yang diberikan; bot tidak melakukan login
ke dashboard web untuk mengambil riwayat.

`TOOLS_PROVIDER_APPLY_STATUS_URL` opsional. Isi hanya endpoint status/result/history yang benar-benar
disediakan provider. Jangan mengisi endpoint action `/api/v1/apply-premium` sebagai status URL.
Jika endpoint baca tidak tersedia, hasil tetap dibaca dari respons POST apply dan dicatat oleh bot.

Pengaturan retry lama tetap tersedia, dengan perilaku baru:
- `TOOLS_PROVIDER_MAX_RETRIES`: retry untuk request baca biasa;
- `TOOLS_PROVIDER_TEMP_RETRIES`: satu lapisan retry untuk polling status yang ditandai read-only;
- POST Kirim Link, Verify Account, Apply Premium, dan Provision tidak diulang otomatis;
- HTTP 202/pending tetap diproses; timeout/5xx apply tetap belum diketahui;
- Refresh Status tidak mengirim apply ulang dan tidak mengganti hasil sukses dengan kegagalan baca.
- HTTP 429 menghentikan polling agar kuota tidak terbuang; ikuti waktu reset/Retry-After provider.

`TOOLS_PROVIDER_HOURLY_LIMIT` sekarang ditegakkan terhadap request HTTP aktual pada SQLite.
`TOOLS_PROVIDER_REQUESTS_PER_ACCOUNT` tetap menjadi estimasi kapasitas akun; tiga request dasar
adalah Kirim Link → Verify Account → Apply Premium. Polling status juga menggunakan kuota.
Histori provision sebelum upgrade dipertahankan dan tetap diperhitungkan pada jam upgrade.

Navigasi di `/tools` mempertahankan session. Link dan idToken hanya berada di memori hingga masa session
habis; hasil, email, Flow ID, guard request, serta wizard harga/stok tetap berada di database.
Setelah restart, bot bisa menampilkan hasil atau membaca status tanpa mengulang apply. Bila belum
apply, verifikasi ulang diperlukan untuk memperoleh idToken baru.

Schema `178`: tabel `tool_provider_requests`, serta kolom `apply_started_at` dan `apply_activity_id`
pada `tool_provider_flows`, serta `request_metered` pada `tool_provision_logs`. Semua tabel lama dan fitur toko tetap tersedia. Backup database v16.51
dapat dibuka oleh v16.52 dan dimigrasikan otomatis saat startup.

## v16.53 — Perbaikan Command dan Runtime

Tidak ada variable baru. Konfigurasi provider v16.52 tetap digunakan; flow `/tools` tidak diganti.
Nama command serta fitur toko lama tetap tersedia. Perubahan command lain hanya memperbaiki bug
Atur Harga, session Harga Custom, validasi callback produk, akses `/owner`, dan renderer Telegram.

Variable angka umum yang kosong atau tidak valid kini memakai nilai default sebelumnya:
`ADMIN_ID=0`, `PORT=8080`, `BACKUP_INTERVAL_HOURS=48`, `BACKUP_RETENTION=20`, dan
`ORDER_RESERVATION_MINUTES=15`. Nilai minimum yang sudah berlaku tetap dipertahankan;
port dibatasi ke 1–65535. `ADMIN_ID=0` menonaktifkan akses owner; isi ID owner yang benar.
Nilai variable valid tetap digunakan. `DB_PATH`/`BACKUP_DIR` kosong memakai path default sebelumnya.

Session Harga Custom aktif tetap persisten saat restart; session yang ditinggalkan melalui
menu owner dibersihkan agar tidak menangkap input wizard lain. Metadata dan hasil tools tetap
persisten; link/idToken tools tetap sementara di memori seperti v16.52.

Schema tetap `178`; tidak ada tabel, fitur, atau file lama yang dihapus.

## v16.54 — Penomoran Rilis dan Panduan Upload

Tidak ada variable baru atau perubahan schema. Versi pada launcher/source kini v16.54;
nama paket `MaboyyDigital_v16.54.zip`. Fitur dan perbaikan runtime v16.53 tetap dipertahankan.
Setiap peningkatan berikutnya menaikkan nomor rilis serta menyelaraskan versi source,
launcher, panduan, dan nama ZIP. Enam nama file di dalam ZIP tetap sama tanpa folder tambahan.
Panduan file yang di-upload ke GitHub serta status integrasi pembayaran ada di README.

## v16.55 — Perbaikan Stok/Slot Famhead

Tidak ada variable, dependensi, atau migrasi schema baru. Schema tetap `178`.
Gunakan `main.py` dan `bot.py` dari paket v16.55 yang sama, lalu redeploy Railway.
Start Command tetap `python main.py`; database pada Volume tetap dipakai.

Tombol +1/+5/+10 kini memperbarui tampilan slot setelah commit tanpa mengubah callback
Telegram. Tambah Custom, tombol Kembali, dan tombol stok lama diperbaiki tanpa mengganti
command. Flow pembayaran dan provider `/tools` tetap seperti versi sebelumnya.

Pada versi sebelumnya, `ValidationError` tambah slot terjadi setelah stok sudah tersimpan.
Periksa jumlah aktual sebelum menambahkan ulang. Rilis ini tidak mengoreksi stok historis
secara otomatis karena jumlah yang sebenarnya diinginkan owner tidak dapat disimpulkan.

## v16.56 — VIP /tools, Magic Link, Rating, dan Input Slot

Tidak ada variable atau dependensi baru. Owner mengatur VIP khusus tools dari `/tools` →
**👑 VIP /tools** → pilih user → **✅ Jadikan VIP /tools**; tidak perlu menambahkan ID user
melalui Railway Variables. VIP ini tidak mengubah level member belanja atau akses command lain.
Izin disimpan dalam database di Volume dan tetap berlaku setelah restart.

Schema `179` menambahkan tabel `tools_user_access` dan `tools_user_reviews` tanpa menghapus
tabel/data lama. Migrasi otomatis saat startup. Enam file flat dan Start Command
`python main.py` tetap digunakan; upload `main.py`/`bot.py` dari paket v16.56 yang sama.

Flow user membutuhkan provider aktif, API key, serta URL Send Magic Link, Verify Account,
dan Apply Premium yang sudah dikonfigurasi. `TOOLS_PROVIDER_APPLY_STATUS_URL` tetap opsional
untuk membaca hasil pending/unknown; tombol Magic Link tidak mengulang request apply tersebut.
Limit request lokal yang sudah ada juga menghitung request user sesuai ID Telegram pelaku.

Panel owner tetap lengkap. User VIP melihat pesan “Gunakan fitur dengan bijak” dan hanya
menu Magic Link, lalu Rating Toko setelah apply sukses. User non-VIP tidak mendapat akses
fitur /tools. User yang diblokir atau izinnya dicabut tidak dapat melanjutkan request baru.
Link/idToken user tetap sementara di memori; credential provider tidak ditampilkan ke user.

Input angka Tambah Slot Pre-Order/Famhead diperbaiki agar tidak ditangkap shortcut produk.
Shortcut tetap tersedia saat tidak ada input aktif. Perbaikan ini tidak memerlukan perubahan
variable Railway atau koreksi stok otomatis; redeploy menggunakan paket v16.56 yang sama.

Tombol nominal saldo terpilih juga diperbaiki agar tidak menampilkan peringatan kedaluwarsa.
Nominal, session, dan alur pembayaran tetap dipertahankan.

## v16.57 — README Ringkas

README diringkas untuk upload, menjalankan bot, dan VIP /tools. Versi launcher/source/paket
diselaraskan ke v16.57; fitur, variable, dependensi, dan schema `179` tetap seperti v16.56.

## v16.58 — Pengaturan Famhead dan Stok

Owner membuka Produk & Stok → Atur Produk untuk mengubah nama/deskripsi, estimasi/arahan,
nama/harga varian, menambah varian, atau membuka slot. Pengaturan teks/harga tidak mengubah
stok/reservasi. Setup slot awal hanya mengisi varian kosong; stok yang sudah ada dipertahankan.
Session setup lama/nonaktif ditolak. Flow Famhead diperiksa sebelum pembayaran dan konfirmasi.
Perbaikan inventory saat restart/recovery tidak lagi menyamakan slot Famhead/Pre-Order dengan
jumlah akun inventory; slot yang ditambahkan tetap tersimpan. Stock ready tetap disinkronkan.
Tidak ada variable/dependensi baru. Schema `180` menambahkan penanda notifikasi undangan
Famhead agar klik ulang tidak mengirim berulang. Migrasi otomatis mempertahankan data lama.
Gunakan enam file dari paket v16.58.

## v16.59 — Rating Toko

Rating checkout dan VIP /tools memakai kartu serta tombol bintang yang seragam.
Owner dapat membaca seluruh ulasan lewat halaman 5 penilaian; ringkasan toko memuat
sebaran bintang dan ulasan terbaru. Validasi callback, duplikasi, status pesanan,
sesi ulasan, serta error database diperbaiki tanpa mengubah alur pembayaran/provider.
Tidak ada variable/dependensi baru; schema tetap `180`. Upload enam file v16.59 bersama.

## v16.60 — Temp Mail Owner

Owner di chat pribadi: /tools → Temp Mail → Buat Email → Received Mail.
Tersedia daftar alamat, salin alamat, domain aktif, serta baca pesan masuk.
API [Mail.tm](https://docs.mail.tm/) gratis tanpa API key, dengan token akun per inbox.
Referensi: [akun](https://docs.mail.tm/api/accounts),
[pesan masuk](https://docs.mail.tm/api/messages),
[alternatif Guerrilla Mail](https://www.guerrillamail.com/GuerrillaMailAPI.html).

- `TEMPMAIL_ENABLED=true` mengaktifkan menu; `false` menahan request provider.
- `TEMPMAIL_TIMEOUT_SECONDS=12` membatasi request (3–30 detik).
- `TEMPMAIL_ENCRYPTION_KEY` opsional, simpan sebagai Railway Secret tetap.
  Jika kosong, enkripsi menggunakan BOT_TOKEN. Pertahankan secret/token yang sama
  untuk membuka inbox lama; database tidak menyimpan password/token email sebagai teks.

Schema `181` menambahkan tabel mailbox owner; migrasi mempertahankan data lama.
Tidak ada dependency baru. Temp Mail tetap khusus owner; VIP /tools tetap Magic Link
dan Rating Toko. Pesan masuk dibaca melalui menu refresh, tanpa apply otomatis.
Provider Mail.tm dicantumkan di menu sesuai persyaratan atribusi API.

Menu utama /tools diringkas; tombol Lainnya tidak ditampilkan. Bersihkan Log Lama
meminta konfirmasi sekali pakai (5 menit) untuk log final owner lebih dari 30 hari.
Hasil apply, flow provider, VIP, rating, inbox, dan data belanja tetap tersimpan.
Riwayat belanja tersedia langsung dari /start dan selesai transaksi; layar
pembayaran/bukti memakai tombol status dan kembali ke transaksi yang sama.

## v16.61 — Riwayat Belanja

Tombol Riwayat tersedia di menu awal dan selesai transaksi; keyboard bawah
tidak mengulang tombol tersebut. Tombol/teks lama memakai halaman yang sama,
dengan detail tiap invoice dan pagination. Kirim ulang akun ada di detail
pesanan selesai. Keluar ke menu/Riwayat mengakhiri input belanja dan sesi
bukti tanpa mengubah pembayaran atau stok. Tombol Kembali user/owner memakai
callback berbeda; callback lama tetap kompatibel. Tidak ada variable atau
dependency baru; schema tetap `181`. Upload enam file v16.61 bersama.

## v16.62 — Aktivasi AM Otomatis

Owner di chat pribadi: /tools → Aktivasi AM Otomatis. Bot membuat Temp Mail,
mengirim Magic Link, membaca link dari inbox, memverifikasi, lalu mengirim Apply Premium sekali.
Hasil final memuat email dan Received Mail/tautan inbox Telegram untuk akun tersebut.
Status sukses harus berasal dari hasil apply provider; target 1 tahun hanya dikonfirmasi
jika paket/masa aktif tersedia dari provider. Endpoint apply tetap memakai email dan idToken.

- `TOOLS_AUTO_AM_MAIL_WAIT_SECONDS=90`: batas menunggu Magic Link masuk ke inbox.
- `TOOLS_AUTO_AM_POLL_SECONDS=3`: jarak pemeriksaan inbox selama menunggu.

Perlu konfigurasi Temp Mail dan endpoint Send Magic Link, Verify Account, Apply Premium,
serta API key provider. Request aksi tidak diulang saat pending/hasil belum diketahui;
lanjutkan melalui status yang tersedia. Password/token inbox tetap terenkripsi dan
link/idToken verifikasi hanya sementara. Pengujian API memakai simulasi; apply asli belum diuji.
Schema `182` menambahkan job aktivasi agar klik ulang/restart tidak mengulang request.
Tidak ada dependency baru. Upload enam file v16.62 bersama.

## v16.63 — Informasi VIP /tools

Layar awal VIP menampilkan teks statis `0/15 akun/jam`; bukan penghitung pemakaian.
Aktivasi sekali klik tetap khusus owner. Tidak ada variable/dependency baru; schema tetap `182`.
Upload enam file v16.63 bersama.

## v16.64 — Pemulihan Temp Mail dan Aktivasi

Format referensi akun Mail.tm yang didukung dinormalisasi; pesan/link rusak tidak menahan pesan valid berikutnya.
Lanjutkan memakai email yang sama dan melaporkan status; Apply yang sudah dikirim tidak diulang.
VIP tetap menampilkan teks statis `0/15 akun/jam`; aktivasi sekali klik khusus owner.
Pengujian memakai API simulasi, bukan aktivasi premium asli. Schema tetap `182`; tidak ada variable/dependency baru.
Upload enam file v16.64 bersama.

Tambahan v16.64: menu owner memakai satu pintu masuk Magic Link / Verifikasi; callback lama tetap berfungsi.
Tautan inbox membuka Received Mail langsung, dan tombol Salin Alamat mengikuti inbox yang sedang dibuka.
Daftar produk, Populer, dan Flash Sale memuat10produk perhalaman dengan tombol langsung;
nomor produk tetap konsisten, Flash kedaluwarsa disaring, dan navigasi menyesuaikan produk yang dinonaktifkan.

## v16.65 — Link inbox situs untuk dibagikan

`TEMPMAIL_PROVIDER=maildrop` memilih Maildrop untuk email baru (default). API GraphQL resmi gratis tanpa API key.
Alamat baru berakhiran `@maildrop.cc`; teks email dan hasil aktivasi menyertakan link
`https://maildrop.cc/inbox/?mailbox=NAMA_EMAIL`. Link dapat Anda bagikan ke pembeli tanpa akses Telegram bot.
Fitur Temp Mail/aktivasi tetap khusus owner, tombol tidak ditambah. Tombol kotak masuk yang sudah ada menuju situs untuk email baru.
`TEMPMAIL_PROVIDER=mailtm` memakai Mail.tm untuk email baru; mailbox Mail.tm lama tetap terbaca apa pun pilihan provider.
Alamat Mail.tm lama tidak dapat dipindahkan ke Maildrop atau diberi link inbox Maildrop.

Maildrop tidak memakai password: siapa pun yang mengetahui alamat dapat membaca/menghapus pesan di situs provider.
Maksimal 10 pesan; pesan dapat dihapus setelah 24 jam tanpa email baru, atau lebih cepat ketika provider penuh.
Pengiriman pertama kadang tertunda 15 menit–1 jam karena greylisting. Bot menunggu sebentar lalu menyediakan Lanjutkan
pada alamat yang sama, tanpa mengirim ulang Magic Link atau Apply. Inbox sementara tidak dijamin tersimpan setahun.
Domain tetap harus diterima oleh provider Alight; sukses/paket mengikuti respons Apply, bukan jenis email.

Sumber: [API](https://docs.maildrop.cc/api-reference/overview), [schema](https://docs.maildrop.cc/api-reference/graphql-api-schema),
[penerimaan](https://maildrop.cc/contact-us/), [batas inbox](https://maildrop.cc/how-it-works/), [privasi](https://maildrop.cc/privacy/).
Schema `183` menandai provider per mailbox; migrasi mempertahankan email lama, job, produk, pembayaran, dan data belanja.
Tidak ada dependency atau webserver baru. Upload enam file v16.65 bersama; jangan upload database atau secret ke GitHub.
API/penerimaan/Apply diuji dengan simulasi; penerimaan Alight dan pembukaan situs inbox asli belum diuji langsung.

Batas email: 5 per provider (maksimal 10 alamat tersimpan). Lima mailbox Mail.tm lama tidak menghalangi email baru Maildrop; daftar lama tetap dapat dipilih.

## v16.66 — Aktivasi AM Pro 1 tahun khusus Maildrop

Aktivasi AM otomatis baru selalu membuat alamat `@maildrop.cc`, mengirim Magic Link, membaca inbox,
memverifikasi link, lalu mengirim Apply Premium satu kali. Hasil memuat email dan link inbox Maildrop yang bisa dibagikan.
`TEMPMAIL_PROVIDER` hanya memilih provider untuk pembuatan Temp Mail manual; tidak mengalihkan aktivasi baru ke Mail.tm.
Job lama yang sudah terikat ke email tetap melanjutkan email tersebut agar Magic Link/verifikasi/Apply tidak diulang.
Menu tetap khusus owner; tidak ada tombol tambahan. Schema tetap `183`, tanpa variable atau dependency baru.
Paket/durasi tetap mengikuti hasil provider; endpoint Apply tidak memiliki parameter jaminan satu tahun.
Pengujian menggunakan API simulasi; penerimaan Alight/Apply asli belum diuji. Upload enam file v16.66 bersama.

## v16.67 — Belanja ringkas dan aktivasi otomatis

Awal `/start` hanya memiliki Belanja dan Rating Toko; Riwayat/Menu Utama tersedia pada daftar produk dan hasil akhir.
Daftar memuat 10 produk per halaman, tanpa tombol nama produk panjang; nomor tetap dapat ditekan/diketik.
Setiap invoice baru membeli 1 unit; pilihan jumlah/MAX dihapus. Jumlah invoice lama tetap dipertahankan.
QRIS pesanan dibatalkan dihapus; jika Telegram menolak, caption dan tombol pembayaran dinonaktifkan.

Aktivasi owner berjalan dari satu klik tanpa konfirmasi ulang. Callback memeriksa inbox sekali agar tidak tertahan;
bot melanjutkan otomatis di background setiap minimal 30 detik selama 1 jam, kemudian mengirim hasil ke chat owner.
Pemantauan dan email tetap tersimpan saat restart; lease mencegah proses paralel mengirim aksi berulang.
Jika belum masuk setelah 1 jam, gunakan Periksa Status pada email yang sama. Jika provider tidak mengirim token
atau hasil Apply belum pasti, bot melaporkan kondisi tersebut dan tidak mengulangi request yang sudah dikirim.
Hasil akhir yang gagal terkirim ke Telegram dicoba lagi tanpa mengulangi Apply.

`TOOLS_AUTO_AM_POLL_SECONDS` tetap diterima; pemeriksaan background minimal 30 detik.
`TOOLS_AUTO_AM_MAIL_WAIT_SECONDS` tetap diterima untuk kompatibilitas konfigurasi lama; callback tidak lagi menunggu inbox 90 detik.
Schema `184` menyimpan batas pemantauan, tujuan pesan, dan status notifikasi. Migrasi otomatis mempertahankan data lama.
Tidak ada dependency baru. Upload enam file v16.67 bersama, dengan Volume/database lama tetap terpasang.

## v16.68 — Grabmail dan aktivasi yang diuji langsung

Aktivasi owner baru memakai Grabmail. Bot membuat alamat acak, mengirim Magic Link, membaca pesan,
memverifikasi, lalu Apply sekali tanpa konfirmasi tambahan. Link hasil membuka
`https://grabmail.io/inbox/NAMA@grabmail.io` dan dapat dibagikan tanpa akses bot.

```env
TEMPMAIL_PROVIDER=grabmail
TOOLS_AUTO_AM_MAIL_PROVIDER=grabmail
TOOLS_PROVIDER_APPLY_TIMEOUT_SECONDS=30
```

Pilihan provider: `grabmail`, `guerrilla`, `mailtm`, atau `maildrop`. Variable aktivasi memilih email baru;
email/job lama tetap terikat pada provider dan alamatnya. Jika aktivasi Maildrop lama masih menunggu email,
klik Aktivasi baru dari /tools dapat menghentikan pemantauan lama dan memulai dengan provider baru;
klik ulang tombol sesi lama tetap memakai email lama. Verifikasi/Apply yang sudah dikirim tidak diulang.

Grabmail memakai REST API tanpa key untuk domain publik; batas gratis 60 request/menit, 1.000/hari per IP,
dan satu baca/detik per alamat. Bot memberi jarak request serta menghormati Retry-After.
Pesan dihapus setelah 5 hari. Guerrilla menyimpan pesan sekitar 1 jam; Mail.tm membutuhkan login situs.
Semua email lama tetap tersimpan; batas lokal 5 per provider, dengan maksimal 20 alamat ditampilkan.

Endpoint Alight yang digunakan: `/api/v1/send-magiclink`, `/api/v1/verify-account`, `/api/v1/apply-premium`.
Alias lama `/send-magic-link` dikoreksi hanya untuk host Alight; URL provider lain tetap mengikuti konfigurasi.
HTTP 4xx, termasuk HTML 404, menjadi kegagalan yang jelas; respons timeout/5xx tetap belum diketahui.
Token bertingkat hasil verify dibaca; masa aktif memakai `expiryTimeMillis` dari hasil provider.

Uji API nyata Mail.tm dan Guerrilla berhasil sampai Apply. Uji Grabmail melalui callback sekali klik kode bot
berhasil dalam sekitar 16,6 detik: tiga aksi HTTP 200, hasil sukses dan link inbox tampil, klik ulang 0 request.
Satu uji Apply dengan batas 12 detik mengalami timeout; tidak diulang. Batas Apply kini terpisah, default 30 detik.
Hasil uji memberi kedaluwarsa 3 Juli 2027; paket satu tahun baru dari hari aktivasi tidak dijanjikan.
Pesan Telegram pada pengujian ditangkap lokal, bukan dikirim ke pembeli/owner asli.

Sumber: [API Grabmail](https://grabmail.io/docs/api), [batas Grabmail](https://grabmail.io/docs/limits),
[API Guerrilla](https://www.guerrillamail.com/GuerrillaMailAPI.html), [API Mail.tm](https://docs.mail.tm/).
Schema tetap `184`; tidak ada dependency atau tombol baru. Upload enam file v16.68 bersama; Volume/database lama tetap dipakai.

## v16.69 — Daftar produk A–Z dan PM owner saat pembeli membatalkan

Daftar utama dan Flash Sale diurutkan berdasarkan nama A–Z, tanpa membedakan huruf besar/kecil.
Nomor daftar, pagination 10 produk, keyboard angka, dan pilihan nomor mengikuti urutan yang sama.
Popular tetap mengikuti jumlah terjual, dengan A–Z untuk nilai yang sama; nomor tetap merujuk daftar utama.
ID produk/database dan callback produk tetap dipertahankan.

Saat pembeli membatalkan pesanan belum dibayar, notifikasi pesanan dan bukti terkait di PM owner dihapus.
ID pesan disimpan untuk cleanup setelah restart dan menangani pesan yang terlambat selesai dikirim.
Jika penghapusan ditolak Telegram, pesan ditandai batal dan tombol tindakan dinonaktifkan;
kegagalan jaringan dicoba lagi. Pesanan dibayar, pesanan milik user lain, dan notifikasi topup tetap aman.
Notifikasi yang dikirim versi lama tanpa ID tersimpan tidak bisa ditemukan melalui Bot API; hapus manual.

Schema `185` menambahkan pencatatan notifikasi owner dan pembatalan pembeli; migrasi menjaga data lama.
Tidak ada variable, dependency, atau tombol baru. Upload enam file v16.69 bersama, tetap memakai Volume/database lama.
