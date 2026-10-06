# Maboyy Digital Bot

**Versi aktif:** v13.5  
**Platform:** Telegram Bot + Railway + SQLite

## Update Terbaru — v13.5 Stok Ringkas
- Jumlah stok tetap ditampilkan pada List Produk.
- Indikator warna/status stok dihapus sesuai permintaan.
- Format list: `Nama Produk — Stok 8`.
- Format tombol: `Nama Produk (8)`.
- Perhitungan stok tetap menggunakan stok tersedia setelah reservasi.
- Tidak menambah query per produk.
- Tidak ada Railway Variable baru.

## File Project
`main.py` • `bot.py` • `requirements.txt` • `.env.example` • `README.md` • `VARIABLE_RAILWAY.md`


## v13.6 — Contoh Catatan Pesanan
- Contoh catatan checkout dibuat lebih umum dan profesional.
- Tidak lagi menggunakan contoh email, profil anak, atau instruksi password.
- Tidak ada perubahan pada alur pembayaran maupun penyimpanan catatan.


## v13.7 — Alur Verifikasi Bukti Pembayaran
- Menghapus instruksi lama `Buka /owner → Verifikasi Bayar` dari notifikasi order.
- Jalur utama verifikasi sekarang tegas: user kirim bukti → PM owner → tombol Konfirmasi/Tolak/Pending.
- Menu Verifikasi Pembayaran owner hanya menampilkan transaksi yang sudah memiliki bukti dan berfungsi sebagai fallback.
- User diberi konfirmasi bahwa tidak perlu membuka /owner atau menghubungi owner untuk verifikasi.
