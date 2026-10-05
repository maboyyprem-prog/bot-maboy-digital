# Maboyy Digital — Telegram Premium Digital Shop

**Author/Brand:** Maboyy Digital  
**Since:** 2020  

Bot toko produk digital sederhana dengan tampilan seperti contoh:
- `/start` menampilkan menu utama.
- Tombol List Produk.
- Tombol Voucher.
- Tombol Laporan Stok.
- Produk ditampilkan bernomor 1, 2, 3, dst.
- Detail harga dan stok.
- Checkout/order manual.
- Notifikasi order ke admin.
- Panel admin.
- SQLite, jadi tidak perlu database eksternal untuk awal.

> Gunakan bot hanya untuk produk, voucher, lisensi, atau akses digital yang legal dan sesuai syarat layanan platform terkait.

## File

Upload file berikut ke GitHub:

1. `bot.py`
2. `requirements.txt`
3. `.env.example`
4. `README.md`

JANGAN upload file `.env` karena berisi token rahasia.

## Setup BotFather

1. Buka `@BotFather`
2. Jalankan `/newbot`
3. Buat nama bot
4. Salin token
5. Buat file `.env` dari `.env.example`
6. Isi:
   - `BOT_TOKEN`
   - `ADMIN_ID`
   - `ADMIN_USERNAME`

## Mengetahui ADMIN_ID

Anda bisa memakai bot Telegram seperti `@userinfobot` untuk melihat ID Telegram Anda.

## Menjalankan lokal

```bash
pip install -r requirements.txt
python bot.py
```

## Deploy Railway

Gunakan variables:

```env
BOT_TOKEN=token_bot_anda
ADMIN_ID=id_telegram_owner
ADMIN_USERNAME=username_telegram_owner
```

Start command:

```bash
python bot.py
```

## Menu pengguna

- `/start` — menu utama
- `/pm` — hubungi admin
- `/voucher KODE` — cek voucher

## Menu admin

- `/admin`
- `/addproduk Nama | Harga | Stok | Deskripsi`
- `/setstok ID JUMLAH`
- `/setharga ID HARGA`
- `/hapusproduk ID`
- `/orders`
- `/addvoucher KODE DISKON`
- `/selesai ID_ORDER`

### Contoh tambah produk

```text
/addproduk Canva Pro Invite | 25000 | 10 | Invite legal ke team.
```

### Contoh ubah stok

```text
/setstok 1 20
```

### Contoh buat voucher

```text
/addvoucher HEMAT10 10000
```

## Catatan pengembangan berikutnya

Versi awal ini sengaja dibuat simpel. Untuk versi lebih profesional bisa ditambah:
- QRIS/payment gateway otomatis.
- Invoice otomatis.
- Pengiriman produk otomatis setelah pembayaran.
- Kategori produk.
- Riwayat pembelian user.
- Dashboard admin berbasis tombol, tanpa command.
- Statistik penjualan.
- Anti-spam/rate limit.
- Backup database.


---
Since 2020