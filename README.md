# Maboyy Produk Digital — Telegram Bot

**Brand:** Maboyy Produk Digital  
**Footer:** Aplikasi Premium • Since 2020  
**Version:** v1.5

Versi ini dibuat lebih sederhana untuk pengguna dan owner.

## Command yang tersedia

Hanya 3 command:

- `/start` — membuka menu utama
- `/owner` — membuka panel owner
- `/ping` — mengecek status bot

Semua pengaturan toko dilakukan melalui tombol di `/owner`.

## Fitur User

- List produk
- Detail produk
- Stok produk
- Order
- Invoice `MBY-000001`
- Pesanan Saya
- Laporan stok
- Tombol hubungi owner
- Status pembayaran/order

## Panel Owner Berbasis Tombol

- Tambah produk
- Atur stok
- Atur harga
- Hapus/nonaktifkan produk
- Lihat pesanan
- Selesaikan order
- Tambah voucher
- Statistik toko

Owner tidak perlu lagi menghafal command seperti `/setstok`, `/setharga`, `/orders`, dan lain-lain.

## Railway Variables

```env
BOT_TOKEN=token_dari_botfather
ADMIN_ID=id_telegram_owner
ADMIN_USERNAME=username_telegram_owner
```

Jangan upload token asli ke GitHub.

## Deploy Railway

Start command:

```bash
python bot.py
```

File yang di-upload ke GitHub:

1. `bot.py`
2. `requirements.txt`
3. `.env.example`
4. `README.md`

Aplikasi Premium • Since 2020
