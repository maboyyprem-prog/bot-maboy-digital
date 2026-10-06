# Maboyy Digital Bot

**Versi aktif:** v10.1  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v10.1 Auto Recovery Layer
- Ditambahkan self-healing yang aman tanpa mengubah source code saat runtime.
- Recovery otomatis paid order yang belum terkirim.
- Auto repair inventory mismatch.
- Reset top up `processing` yang nyangkut ke `pending`.
- Bersihkan payment proof session stale.
- SQLite integrity check setiap recovery cycle.
- Jika recovery kritis gagal, bot otomatis mengaktifkan Safe Mode.
- Error runtime mencoba auto recovery sebelum owner mengambil tindakan.
- Auto recovery periodik setiap 10 menit.
- Ditambahkan tombol `♻️ Auto Recovery` di menu Sistem owner.
- Tidak ada Railway Variable baru.

## Command
User: `/start`  
Owner: `/owner` • `/ping`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
