# Maboyy Digital Bot

**Versi aktif:** v12.1  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v12.1 Deployment Fingerprint
- Memastikan `import re` tersedia dan parser tetap memiliki local fallback import.
- Startup menjalankan source-integrity + dependency self-test sebelum polling.
- Railway log sekarang mencetak banner `MABOYY DIGITAL STARTUP v12.1`.
- Log startup mencetak Deployment ID, Replica ID, commit GitHub, environment, source file, dan DB path.
- `/ping` menampilkan versi kode yang BENAR-BENAR sedang berjalan.
- `/health` menampilkan `bot_version`, deployment ID, replica ID, commit, environment, dan DB path.
- Diagnostik Sistem menampilkan Bot Version + Railway Deployment ID + commit.
- Jika Railway masih menjalankan deployment lama, sekarang langsung terlihat tanpa menebak dari log.
- Semua hardening v12.0 tetap dipertahankan.
- Tidak ada Railway Variable baru; fingerprint memakai variable bawaan Railway.

## Command
User: `/start` • `/demo`  
Owner: `/owner` • `/ping` • `/demo`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
