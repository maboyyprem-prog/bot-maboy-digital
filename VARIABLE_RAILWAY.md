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
