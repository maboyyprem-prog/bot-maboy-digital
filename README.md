# Maboyy Digital Bot

**Versi aktif:** v14.2  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v14.2 Kode Unik Rp200–Rp500
- Kode unik pembayaran sekarang selalu berada di rentang `+Rp200` sampai `+Rp500`.
- Kode tidak pernah di bawah Rp200 dan tidak pernah lebih dari Rp500.
- Setelah mencapai 500, sistem berputar kembali ke 200.
- Kode yang sedang dipakai transaksi aktif tidak akan dipakai ulang.
- Setting lama otomatis dimigrasikan ke `min=200` dan `max=500`.
- Berlaku untuk order dan top up.
- Tidak ada Railway Variable baru.

## File Project
`main.py` • `bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
