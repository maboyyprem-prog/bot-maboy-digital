# Maboyy Digital Bot

**Versi aktif:** v11.6  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v11.6 Demo Isolation Lock
- `/demo` tetap 100% simulasi untuk user dan owner.
- Semua callback demo diwajibkan berada di namespace `userdemo:*`.
- Demo callback tidak boleh memanggil fulfillment, mark paid, topup verification, inventory sync, atau database produksi.
- Audit AST memastikan callback demo tidak memiliki callback menuju flow produksi.
- `/start` diaudit tidak memiliki referensi demo.
- Ditambahkan safety-net untuk callback `userdemo:*` yang tidak dikenal; bot menolak tanpa mengubah data.
- Akun demo tetap string palsu tetap, tidak pernah mengambil inventory resmi.
- Tidak ada produk/order/topup/saldo/stok resmi yang dibuat atau diubah oleh demo.
- Tidak ada Railway Variable baru.

## Command
User: `/start` • `/demo`  
Owner: `/owner` • `/ping` • `/demo`

## File Project
`bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`
