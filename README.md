# Maboyy Digital Bot

**Versi aktif:** v11.7  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v11.7 Runtime Import Guard
- Memastikan `import re` tersedia tepat satu kali.
- Parser harga sekarang memakai local import `_re` sebagai pertahanan tambahan.
- Ditambahkan `runtime_dependency_self_test()` sebelum polling.
- Startup akan gagal lebih awal bila `re`, timezone, main menu, parser harga, atau fulfillment core tidak tersedia.
- Parser 2500 / 2.500 / Rp2.500 / 15,000 lolos smoke test.
- Demo Isolation v11.6 tetap dipertahankan.
- Tidak ada Railway Variable baru.

## Command
User: `/start` • `/demo`  
Owner: `/owner` • `/ping` • `/demo`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
