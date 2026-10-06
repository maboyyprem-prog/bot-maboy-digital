# Maboyy Digital Bot

**Versi aktif:** v7.4  
**Platform:** Telegram Bot + Railway + SQLite

## Fitur Utama
- Produk digital, stok akun, wallet, top up, voucher, promo, rating.
- QRIS / transfer rekening dengan bukti pembayaran ke PM owner.
- Invoice pembayaran berhasil berupa gambar profesional.
- Recovery, backup, Safe Mode, maintenance, dan diagnostik.
- Panel owner hanya dapat diakses owner.

## Command
```text
/start
/owner
/ping
```

## Deploy
Upload semua file versi terbaru ke GitHub lalu redeploy Railway.

## Update Terbaru — v7.4
- Memperbaiki crash `ModuleNotFoundError: No module named 'PIL'`.
- `Pillow==11.3.0` dipastikan ada di `requirements.txt`.
- Bot tidak lagi crash jika Pillow belum tersedia.
- Invoice otomatis fallback ke teks jika renderer gambar belum tersedia.
- Diagnostik sistem menampilkan status Invoice Image.
- Tidak ada Railway Variable baru.

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
