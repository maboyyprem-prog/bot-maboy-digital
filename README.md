# Maboyy Produk Digital — Telegram Bot

**Version:** v2.8  
**Footer:** Aplikasi Premium • Since 2020

## Command

Tetap hanya:

- `/start`
- `/owner`
- `/ping`

## Update v2.0 — Saldo Kamu

### Fitur User

- 💰 Saldo Kamu
- ➕ Top Up Saldo
- 📑 Riwayat Saldo
- 🛒 Bayar langsung menggunakan Saldo Kamu
- Saldo otomatis berkurang saat pembelian berhasil
- Refund otomatis ke saldo jika proses order gagal
- Top up melalui QRIS manual + kode unik

### Fitur Owner

`/owner → 💰 Manajemen Saldo`

Tersedia:

- Tambah saldo user
- Kurangi saldo user
- Verifikasi top up
- Riwayat transaksi saldo
- Total saldo tersimpan
- Jumlah top up pending

Semua perubahan saldo dicatat dalam ledger sehingga lebih mudah diaudit.

## Pembayaran

Tampilan customer menggunakan nama generik:

- 💰 Saldo Kamu
- 🟡 QRIS Manual
- ⚡ QRIS Otomatis

Nama provider/payment gateway tidak ditampilkan ke customer.

Integrasi otomatis tetap dipersiapkan di backend dan dapat diaktifkan setelah credential resmi tersedia.

## Keamanan Saldo

- Saldo tidak boleh minus
- Setiap transaksi mempunyai reference
- Ledger transaksi mencegah transaksi yang sama diproses dua kali
- Top up yang sudah diverifikasi tidak dapat dikreditkan dua kali
- Pembelian menggunakan saldo langsung ditandai paid jika berhasil
- Jika fulfillment gagal, saldo direfund otomatis

## Railway Variables

Variable lama tetap:

```env
BOT_TOKEN=
ADMIN_ID=
ADMIN_USERNAME=
PAYMENT_NOTE=QRIS Maboyy Digital
```

Variable Payment Gateway otomatis tetap opsional dan tidak perlu diaktifkan sekarang.

## Start Command

```bash
python bot.py
```

## File v2.0

File yang berubah dan perlu diganti di GitHub:

- bot.py
- README.md

File yang tidak berubah dari v1.8:

- requirements.txt
- .env.example

Aplikasi Premium • Since 2020


## Update v2.1 — Verifikasi Join Channel

Saat user menjalankan `/start`, bot akan mengecek apakah user sudah join channel wajib.

Jika belum join:

```text
🔐 VERIFIKASI CHANNEL

Untuk menggunakan Maboyy Produk Digital,
silakan join channel terlebih dahulu.

[ 📢 Join Channel ]
[ ✅ Saya Sudah Join ]
```

Setelah user menekan `✅ Saya Sudah Join`, bot memeriksa membership menggunakan Telegram API.

Jika sudah join:
- status otomatis terverifikasi
- menu utama langsung dibuka

Jika belum:
- muncul notifikasi untuk join terlebih dahulu
- user dapat mencoba lagi tanpa mengetik command baru

### Railway Variables

Tambahkan:

```env
REQUIRED_CHANNEL_ID=@usernamechannel
REQUIRED_CHANNEL_URL=https://t.me/usernamechannel
REQUIRED_CHANNEL_NAME=Maboyy Digital
```

Untuk channel private, `REQUIRED_CHANNEL_ID` dapat menggunakan numeric chat ID, misalnya:

```env
REQUIRED_CHANNEL_ID=-1001234567890
```

Agar bot dapat mengecek membership dengan stabil, tambahkan bot ke channel sebagai admin.



## Update v2.2 — Minimum Top Up

Minimum top up saldo default sekarang:

```text
Rp5.000
```

Jika user memasukkan nominal di bawah Rp5.000, bot akan menolak transaksi.

Owner juga dapat mengubah minimum top up tanpa edit kode:

```text
/owner
→ 💰 Manajemen Saldo
→ ⚙️ Minimum Top Up
```

Default:

```text
5000
```

Nilai minimum tersimpan di database bot.


## Update v2.3 — Tombol Kembali di Panel Owner

Setiap submenu pada `/owner` sekarang memiliki tombol:

```text
⬅️ Kembali
```

Tombol tersebut akan membawa owner kembali ke panel utama `/owner` tanpa perlu mengetik command lagi.

Submenu yang menggunakan tombol kembali antara lain:

- Tambah Produk
- Tambah Variasi
- Atur Stok
- Atur Harga
- Hapus Produk
- Pesanan
- Verifikasi Pembayaran
- Produk Populer
- Flash Sale
- Voucher
- Pengaturan Pembayaran
- Manajemen Saldo
- Minimum Top Up
- Status Payment Gateway
- Pengaturan QRIS
- Riwayat Saldo


## Update v2.5 — Backup, Persistensi Data & Stok Otomatis

### 1. Data tetap tersimpan saat update/redeploy

Gunakan **Railway Volume** dan mount ke:

```text
/data
```

Kemudian isi Railway Variables:

```env
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
```

Dengan ini database aktif berada di Volume, bukan filesystem sementara deployment.

Yang tetap tersimpan:
- user/wallet
- saldo dan ledger
- top up
- order
- produk dan variasi
- voucher
- QRIS tersimpan
- pengaturan bot
- status announcement
- message ID stok channel

Saat pertama berpindah ke Volume, bot juga mencoba menyalin `shop.db` lama ke lokasi persisten jika file lama masih tersedia.

### 2. Backup otomatis

Default:

```env
BACKUP_INTERVAL_HOURS=48
BACKUP_RETENTION=20
```

Bot membuat snapshot SQLite yang aman menggunakan SQLite backup API.

Backup dapat dikirim otomatis ke:

```env
```


Backup otomatis selalu dikirim langsung ke PM owner berdasarkan `ADMIN_ID`.

Owner juga punya tombol:

```text
/owner
→ 🗄️ Backup Sekarang
```

### 3. Stok terbaru otomatis di channel

Isi:

```env
STOCK_CHANNEL_ID=@usernamechannel
```

Bot membuat satu pesan stok dan selanjutnya **mengedit pesan yang sama**, sehingga channel tidak penuh spam.

Stok otomatis disinkronkan saat:
- produk ditambah
- variasi ditambah
- stok diubah
- harga diubah
- produk dinonaktifkan
- order selesai
- pembayaran berhasil

Owner juga dapat memaksa refresh:

```text
/owner
→ 📢 Sinkron Stok Channel
```

### 5. Izin Channel

Bot harus menjadi admin pada channel update/stok agar bisa:
- mengirim pesan
- mengedit pesan stok

### Railway Variables baru

```env
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
BACKUP_INTERVAL_HOURS=48
BACKUP_RETENTION=20

STOCK_CHANNEL_ID=
```

## Perubahan v2.5

Fitur pengumuman update bot otomatis ke channel telah dihapus.

Fitur yang tetap aktif:

- Database persisten melalui Railway Volume
- Backup otomatis
- Backup manual dari panel owner
- Stok terbaru otomatis di channel
- Sinkron stok manual dari panel owner
- Data user, saldo, order, produk, voucher, dan pengaturan tetap tersimpan saat redeploy


## Update v2.6 — Backup Setiap 2 Hari

Backup otomatis sekarang berjalan setiap:

```text
48 jam
```

Railway Variable:

```env
BACKUP_INTERVAL_HOURS=48
```

Backup manual tetap tersedia:

```text
/owner
→ 🗄️ Backup Sekarang
```


## Update v2.7 — Backup Hanya ke PM Owner

Backup otomatis tidak lagi menggunakan channel backup.

Setiap 48 jam file database dikirim langsung ke akun owner berdasarkan:

```env
ADMIN_ID=
```

Variable `BACKUP_CHANNEL_ID` tidak diperlukan lagi.

Backup manual dari:

```text
/owner
→ 🗄️ Backup Sekarang
```

juga dikirim langsung ke PM owner.


## Update v2.8 — Checkout & Pembayaran Lebih Aman

Perbaikan difokuskan pada alur user membeli dan membayar agar tidak mudah terjadi error.

### Checkout aman

- Validasi ulang produk aktif sebelum checkout.
- Validasi ulang stok tepat sebelum order dibuat.
- Proteksi double-tap/double checkout per user.
- QRIS Manual dan QRIS Otomatis menggunakan reservasi stok.
- Stok tersedia = stok fisik dikurangi stok yang sedang direservasi.

### Reservasi stok

Default:

```env
ORDER_RESERVATION_MINUTES=15
```

Selama order QRIS masih pending, stok customer direservasi selama 15 menit.

Jika tidak dibayar sampai batas waktu:

- order menjadi `expired`
- stok reservasi dilepas otomatis
- stok kembali tersedia
- user mendapat notifikasi

### Pembayaran Saldo Kamu

Pembayaran saldo sekarang dilakukan dalam satu transaksi database.

Bot baru menyimpan perubahan jika seluruh langkah berhasil:

1. cek produk
2. cek stok
3. cek saldo
4. buat invoice
5. potong saldo
6. catat ledger
7. kurangi stok
8. tambah jumlah terjual
9. tandai paid/completed

Ini mencegah kasus saldo terpotong tetapi order gagal.

### Proteksi pembayaran ganda

Order yang:
- sudah completed
- expired
- cancelled
- payment_error

tidak akan diproses ulang secara tidak sengaja.

### QRIS Otomatis gagal

Jika pembuatan QR otomatis gagal:

- reservasi stok dilepas
- order ditandai `payment_error`
- customer diarahkan ke QRIS Manual

### File v2.8

Wajib diganti:

- `bot.py`
- `.env.example`
- `README.md`

Tidak berubah:

- `requirements.txt`
