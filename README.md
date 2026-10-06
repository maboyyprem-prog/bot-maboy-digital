# Maboyy Digital Bot

**Versi aktif:** v10.8  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v10.8 Button Reliability Pack
- `allowed_updates` dipaksa eksplisit `message` + `callback_query`.
- Semua callback handler diaudit agar memiliki acknowledgement.
- Memperbaiki 3 handler user yang sebelumnya tidak ACK: Produk, Populer, Flash.
- Callback Trace Middleware mencatat callback terakhir, status handled/error, user, dan latency.
- Diagnostik Sistem dapat membedakan callback tidak sampai ke bot vs callback masuk lalu handler error.
- Event Isolation, persistent FSM, WAL, backoff, concurrency limit tetap aktif.
- Tidak ada Railway Variable baru.

## Command
User: `/start`  
Owner: `/owner` • `/ping`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
