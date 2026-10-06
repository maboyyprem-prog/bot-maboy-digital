# Maboyy Digital Bot

**Versi aktif:** v13.2  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v13.2 Backup Project
- Menu `/owner → ⚙️ Sistem` sekarang memiliki dua backup terpisah:
  - `🗄️ Backup Database`
  - `📦 Backup Project`
- `📦 Backup Project` membuat ZIP flat berisi:
  - `main.py`
  - `bot.py`
  - `requirements.txt`
  - `.env.example`
  - `README.md`
  - `VARIABLE_RAILWAY.md`
  - `shop.db` (snapshot database saat tombol ditekan)
- ZIP dikirim langsung ke PM owner.
- `.env`, BOT_TOKEN, password, private key, dan secret Railway tidak dimasukkan ke ZIP.
- Backup database otomatis setiap 48 jam tetap berjalan seperti sebelumnya.
- Project backup manual memakai retention yang sama agar folder backup tidak tumbuh tanpa batas.
- Tidak ada Railway Variable baru.

## File Project
`main.py` • `bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
