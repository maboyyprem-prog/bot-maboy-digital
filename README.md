# Maboyy Digital Bot

**Versi aktif:** v12.2  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v12.2 Railway Entrypoint Fix
- Menambahkan `main.py` root launcher khusus Railway/Railpack.
- Railway yang otomatis memilih `main.py` sekarang tetap menjalankan `bot.py` terbaru.
- `main.py` memeriksa bahwa `bot.py` benar-benar versi v12.2 sebelum bot dijalankan.
- Jika `main.py` baru tetapi `bot.py` masih lama, deployment gagal dengan pesan `bot.py version mismatch` yang jelas.
- Launcher juga mengetes parser `Rp2.500 -> 2500` sebelum polling.
- Startup log menampilkan `main.py -> bot.py v12.2`, Railway Deployment ID, dan commit SHA.
- `bot.py` tetap memiliki global `import re` + local fallback `_re`.
- Semua hardening v12.1/v12.0 tetap dipertahankan.
- Tidak ada Railway Variable baru.

## WAJIB DI-UPLOAD KE ROOT GITHUB
`main.py` dan `bot.py` harus di-upload bersama. Jangan hanya mengganti `bot.py`.

## Command
User: `/start` • `/demo`  
Owner: `/owner` • `/ping` • `/demo`

## File Project
`main.py` • `bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
