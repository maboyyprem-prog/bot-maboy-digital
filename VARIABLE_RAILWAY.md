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
