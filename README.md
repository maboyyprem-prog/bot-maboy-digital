# Maboyy Digital Bot

**Versi aktif:** v11.0  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v11.0 Runtime NameError Audit
- Memperbaiki `NameError: name 're' is not defined` pada Harga Custom.
- Menambahkan `import re` yang memang dibutuhkan `parse_rupiah_input()`.
- Menambahkan `JAKARTA_TZ = ZoneInfo("Asia/Jakarta")` yang sebelumnya dipakai tetapi belum didefinisikan.
- Menambahkan `main_menu()` yang sebelumnya dipanggil di banyak flow user tetapi belum ada.
- Memperbaiki `expiry_text` pada checkout QRIS.
- Menghapus dead legacy code `startup_recovery_audit` yang masih mereferensikan `results`.
- Merapikan duplicate import `TelegramRetryAfter`.
- Menambahkan symbol-table audit: unresolved global symbol harus 0 sebelum rilis.
- Parser harga, timezone, callback menu, dan SQLite insert smoke test lolos.
- Persistent FSM, Callback Trace, WAL, event isolation, backoff, dan Error Analytics tetap dipertahankan.
- Tidak ada Railway Variable baru.

## Command
User: `/start`  
Owner: `/owner` • `/ping`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
