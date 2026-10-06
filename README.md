# Maboyy Digital Bot

**Versi aktif:** v15.4

## v15.4 — Owner UI Simplification

Fokus versi ini bukan menambah banyak fitur baru, tetapi membuat panel owner lebih sederhana tanpa menghapus fungsi lama.

### Menu utama owner
- 📦 Produk & Stok
- 🧾 Order
- 💳 Pembayaran
- 👥 Pelanggan
- 📊 Dashboard
- 🛟 Recovery
- ⚙️ Sistem
- 🔎 Cari
- 🏠 Menu User

### Perubahan utama
- Produk & Stok dibuat ringkas; fitur jarang dipakai masuk `🧰 Lainnya`.
- Order dipisahkan dari Pembayaran.
- Dibuat `🛟 Recovery Center` untuk order bermasalah.
- Promo/Voucher dipindahkan ke submenu khusus.
- Sistem utama dibuat ringkas; backup/maintenance/test dipindahkan ke `🧰 Sistem Lanjutan`.
- `🧹 Bersihkan Data Aman` dapat diakses langsung dari Sistem dan tetap memakai preview + konfirmasi.
- Semua callback dan fitur versi sebelumnya tetap dipertahankan.

### Catatan keamanan
`Bersihkan Data Aman` tidak menghapus order paid/completed, saldo user, review, atau akun terjual.

Tidak ada Railway Variable baru.
