# Maboyy Digital Bot

**Versi aktif:** v16.32

## v16.32 — Flash Sale Berjangka

Flash Sale sekarang memakai timer persisten di database.

### Owner
Pilih `Produk & Stok > Lainnya > Flash Sale`, lalu pilih produk dan durasi:
- 15 menit
- 30 menit
- 1 jam
- 3 jam
- 6 jam
- 12 jam
- 24 jam
- Custom 1–10080 menit (maks. 7 hari)
- Matikan Flash Sale

Memilih durasi baru mengganti timer lama.

### Auto Expiry
- Waktu akhir disimpan sebagai Unix timestamp di SQLite.
- Restart/redeploy Railway tidak mereset timer.
- Produk expired otomatis tidak ditampilkan di menu Flash Sale.
- Saat menu Flash Sale dibuka, flag expired juga dibersihkan dari database.
- Legacy Flash Sale ON tanpa timer dinonaktifkan saat migrasi agar tidak aktif tanpa batas.

### User
- Menu Flash Sale hanya menampilkan produk yang timer-nya masih aktif.
- Halaman Flash Sale menampilkan waktu berakhir terdekat dalam WIB.
- Detail produk menampilkan waktu berakhir jika produk sedang Flash Sale.

Semua fitur v16.31 tetap dipertahankan.
Schema naik ke 173.
Tidak ada Railway Variable baru.
