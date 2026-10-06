# Maboyy Digital Bot

**Versi aktif:** v9.3  
**Platform:** Telegram Bot + Railway + SQLite

## Fitur Utama
- Produk digital, stok akun, wallet, top up, voucher, promo.
- Verifikasi channel sebelum akses toko.
- QRIS / transfer rekening dengan bukti pembayaran ke PM owner.
- Recovery, backup, Safe Mode, maintenance, diagnostik, dan pembersihan data.

## Command
User: `/start`  
Owner: `/owner` • `/ping`

## Update Terbaru — v9.3
- Memperbaiki error Tambah Produk/Variasi pada langkah harga.
- Menambahkan migration `products.created_at` yang sebelumnya belum ada.
- Create product memiliki fallback untuk database Railway lama.
- Preset harga dan harga custom memiliki error handling sendiri.
- Error wizard tidak lagi langsung jatuh ke popup gangguan umum.
- Tidak ada Railway Variable baru.

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
