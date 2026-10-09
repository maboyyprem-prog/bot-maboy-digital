# Maboyy Digital

**Versi: v16.74** — pembaruan keyboard dan pergantian katalog dirapikan. Petunjuk lama sebelum upgrade yang ID-nya tidak tersimpan dapat dihapus manual.

## Upload GitHub

Upload tepat **6 file flat** dari ZIP langsung ke root GitHub: `main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.
Jangan upload `.env` asli, database, Full Backup, token/API key, log, cache, atau ZIP sebagai source.

## Migrasi Railway

1. Salin nilai Variables lama secara pribadi; `.env.example` hanya daftar nama/contoh, bukan pengganti nilai lama.
2. Simpan Full Backup lama dari `/owner` → **Sistem** → **Backup Project**. ZIP ini privat: berisi seluruh database.
3. Hentikan proses bot lama sebelum snapshot final. Pasang Volume baru `/data`; restore `shop.db` sebelum bot baru dijalankan.
4. Gunakan `DB_PATH=/data/shop.db`, `BACKUP_DIR=/data/backups`, Start Command `python main.py`; aktifkan hanya satu instance.
5. Pertahankan `BOT_TOKEN` dan kunci enkripsi inbox. Jika domain berubah, sesuaikan callback pembayaran pada service baru/provider.

Panduan restore, seluruh nama Variables, pemeriksaan data dan rollback: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md#persiapan-migrasi-v1670).
Paket source tidak memuat database produksi; pengujian memakai database sementara, tanpa deploy/restore produksi otomatis.

Awal `/start`: Belanja dan Rating. Produk normal A–Z: 10 per halaman. Flash Sale aktif tampil khusus menu Flash Sale; nomor pilihan mengikuti daftar yang sedang dibuka.
Tombol produk panjang dan pilihan jumlah/MAX dihapus; setiap invoice baru berisi 1 unit.
Daftar produk tetap menyediakan Keranjang, Paket Hemat, dan Riwayat, tanpa Menu Utama/Favorit. Menu Utama hasil akhir kembali ke `/start`.
Pembatalan pesanan menghapus QRIS dan notifikasi pesanan di PM owner; jika Telegram menolak penghapusan, pesan ditandai batal dan tombol dinonaktifkan. Pesan lama yang ID-nya belum tersimpan perlu dihapus manual.
Gunakan `main.py` dan `bot.py` dari paket versi yang sama. `/ping` khusus owner menampilkan uptime proses; isi `HOSTING_PLAN_NAME` dan `HOSTING_PLAN_EXPIRES_AT` di Railway untuk sisa hari paket. Tanggal paket diisi manual; [format dan contoh](VARIABLE_RAILWAY.md#ping-dan-paket-railway-v1671).

Owner: `/tools` → **👑 VIP /tools** → pilih ID → **✅ Jadikan VIP /tools**; **🚫 Cabut VIP /tools** menghentikan akses.
VIP khusus `/tools` di chat pribadi; informasi awal menampilkan teks statis **0/15 akun/jam**. Aktivasi sekali klik tetap khusus owner.
User VIP: **Magic Link** → email → kirim link → salin URL dari inbox ke bot → **Proses Magic Link** → verifikasi dan Apply Premium otomatis.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.
Owner memakai satu tombol **Magic Link / Verifikasi**. Pertahankan endpoint dan API key provider Railway lama.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, varian, harga, dan slot; stok/reservasi tetap tersimpan. Slot yang sudah hilang sebelum upgrade perlu diisi sesuai jumlah sebenarnya.

## Temp Mail dan aktivasi AM owner

`/tools` → **Temp Mail** → **Buat Email** → **Received Mail** → pilih pesan.
Saat migrasi, pertahankan nilai `TEMPMAIL_PROVIDER` dan `TOOLS_AUTO_AM_MAIL_PROVIDER` lama; contoh default memakai Grabmail.
**Aktivasi AM Otomatis** → email Grabmail → Magic Link → inbox → verifikasi → Apply Premium, tanpa konfirmasi tambahan.
Jika email belum masuk, bot memeriksa otomatis setiap 30 detik sampai 1 jam; hasil akhir dikirim ke chat owner. Pemantauan tersimpan setelah restart.
Email dan hasil aktivasi memuat link situs inbox yang dapat dibagikan; menu tetap khusus owner, tanpa tombol tambahan.
Grabmail gratis tanpa API key; pesan dihapus setelah 5 hari. [API dan batas layanan](https://grabmail.io/docs/api).
Email Maildrop, Mail.tm, dan Guerrilla tetap didukung; batas 5 email per provider. Mail.tm memakai login, tanpa link inbox publik.
**Bersihkan Log Lama** meminta konfirmasi; inbox, hasil apply, rating, dan data belanja tetap tersimpan.
Sukses/masa aktif mengikuti respons provider; tanggal kedaluwarsa ditampilkan, tanpa menjanjikan satu tahun baru.
Apply menunggu hingga 30 detik (`TOOLS_PROVIDER_APPLY_TIMEOUT_SECONDS`); request yang hasilnya belum pasti tidak diulang.
Isi saldo: nominal → QRIS/rekening → bukti → verifikasi owner. Caption QRIS tetap berupa invoice; klik berulang memakai invoice aktif. Saat gambar gagal, kontrol invoice tetap tersedia. Fitur lama dipertahankan.
