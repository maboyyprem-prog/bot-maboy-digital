# Maboyy Digital Bot

**Versi aktif:** v15.0  
**Platform:** Telegram Bot + Railway + SQLite

## Update Besar v15.0
### 📚 Riwayat Akun Terjual
- Menampilkan akun yang benar-benar sudah berstatus `sold`.
- Terhubung ke order ID, user ID, produk, varian, dan waktu delivery.
- Histori tetap tersimpan di SQLite.

### 📊 Dashboard Stok Pintar
- Total varian aktif.
- Total available, reserved, sold.
- Stok rendah dan stok kosong.
- Produk terlaris.
- Daftar varian yang perlu restock.

### ♻️ Refund & Replacement
- Menambahkan tabel klaim support agar kasus refund/replacement dapat dicatat terpisah dari order.
- Menu owner tersedia untuk melihat histori klaim.

### 🧾 Order Detail Profesional
- Struktur detail order diperjelas.
- Status pembayaran, fulfillment, produk, varian, qty dan histori tetap dipertahankan.

### 🔐 Payment Reconciliation
- Audit order aktif dan kode unik pembayaran Rp200–Rp500.
- Deteksi kode unik bentrok pada transaksi aktif.
- Tabel event reconciliation tersedia untuk pengembangan integrasi pembayaran otomatis berikutnya.

### 👤 Customer Profile
- Helper profil customer menyediakan total order, sukses, batal, total belanja, saldo, dan order terakhir.
- Menu customer profile ditambahkan di panel owner.

### 🛡️ Audit & Anti Double Order
- Audit log owner diperkuat.
- Guard checkout aktif dipertahankan dan pesan dibuat lebih jelas.
- Stock source-of-truth tetap `inventory_items`.
- Fulfillment tetap menggunakan jalur aman existing.

### Fitur sebelumnya yang tetap dipertahankan
- Bulk stok Private/Unique.
- Sharing qty guard.
- OWNER_FREE.
- Kode unik pembayaran Rp200–Rp500.
- Terjual persisten dari order history.
- Backup database/project.
- Recovery order.
- Payment proof PM owner.

Tidak ada Railway Variable baru.
