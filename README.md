# Maboyy Digital Bot

**Versi aktif:** v10.9  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v10.9 Price Routing Fix
- Menghapus broad `@router.message(F.text)` recovery handlers yang dapat menangkap pesan lalu berhenti tanpa respons.
- Harga Custom sekarang memakai custom filter `OwnerPriceSessionFilter`.
- Handler Harga Custom persisten diprioritaskan sebelum handler FSM harga.
- Saat nominal masuk, bot langsung menampilkan `MEMPROSES HARGA...`.
- Jika proses gagal, tipe dan detail error langsung ditampilkan.
- Smoke test SQLite untuk harga `2500` → produk + varian berhasil.
- Persistent FSM, Callback Trace, WAL, event isolation, backoff tetap dipertahankan.
- Tidak ada Railway Variable baru.

## Command
User: `/start`  
Owner: `/owner` • `/ping`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
