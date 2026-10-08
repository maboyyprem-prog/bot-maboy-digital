# Maboyy Digital

**Versi: v16.68** — Aktivasi otomatis memakai Grabmail; fitur lama tetap tersedia.

## Upload GitHub

Upload enam file dari ZIP langsung ke root GitHub: `main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.

Simpan token/API key di Railway. Jangan upload `.env`, database, backup, log, cache, atau ZIP sebagai source.

## Jalankan di Railway

1. Isi `BOT_TOKEN` dan `ADMIN_ID` sesuai `.env.example`. File contoh tidak otomatis mengisi Railway.
2. Pasang Volume `/data`; isi `DB_PATH=/data/shop.db` dan `BACKUP_DIR=/data/backups`.
3. Gunakan Start Command: `python main.py`.

Awal `/start`: Belanja dan Rating. Daftar produk: 10 per halaman, pilih lewat nomor.
Tombol produk panjang dan pilihan jumlah/MAX dihapus; setiap invoice baru berisi 1 unit.
Riwayat/Menu Utama tersedia pada daftar produk dan hasil akhir transaksi.
Pembatalan pesanan menghapus gambar QRIS atau menonaktifkan tombol dan menandai caption jika penghapusan ditolak.
Konfigurasi: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md); gunakan `main.py` dan `bot.py` dari paket yang sama.

Owner: `/tools` → **👑 VIP /tools** → pilih ID → **✅ Jadikan VIP /tools**; **🚫 Cabut VIP /tools** menghentikan akses.

VIP khusus `/tools` di chat pribadi; informasi awal menampilkan teks statis **0/15 akun/jam**. Aktivasi sekali klik tetap khusus owner.

User VIP: **Magic Link** → email → kirim link → salin URL dari inbox ke bot → **Proses Magic Link** → verifikasi dan Apply Premium otomatis.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.

Owner memakai satu tombol **Magic Link / Verifikasi**. Isi endpoint dan API key provider di Railway.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, varian, harga, dan slot; stok/reservasi tetap tersimpan. Slot yang sudah hilang sebelum upgrade perlu diisi sesuai jumlah sebenarnya.

## Temp Mail dan aktivasi AM owner

`/tools` → **Temp Mail** → **Buat Email** → **Received Mail** → pilih pesan.
Di Railway isi `TEMPMAIL_PROVIDER=grabmail` dan `TOOLS_AUTO_AM_MAIL_PROVIDER=grabmail`.
**Aktivasi AM Otomatis** → email Grabmail → Magic Link → inbox → verifikasi → Apply Premium, tanpa konfirmasi tambahan.
Jika email belum masuk, bot memeriksa otomatis setiap 30 detik sampai 1 jam; hasil akhir dikirim ke chat owner. Pemantauan tersimpan setelah restart.
Email dan hasil aktivasi memuat link situs inbox yang dapat dibagikan; menu tetap khusus owner, tanpa tombol tambahan.
Grabmail gratis tanpa API key; pesan dihapus setelah 5 hari. [API dan batas layanan](https://grabmail.io/docs/api).
Email Maildrop, Mail.tm, dan Guerrilla tetap didukung; batas 5 email per provider. Mail.tm memakai login, tanpa link inbox publik.
**Bersihkan Log Lama** meminta konfirmasi; inbox, hasil apply, rating, dan data belanja tetap tersimpan.
Sukses/masa aktif mengikuti respons provider; tanggal kedaluwarsa ditampilkan, tanpa menjanjikan satu tahun baru.
Apply menunggu hingga 30 detik (`TOOLS_PROVIDER_APPLY_TIMEOUT_SECONDS`); request yang hasilnya belum pasti tidak diulang.
Uji API nyata melalui alur sekali klik Grabmail berhasil: kirim → terima → verifikasi → Apply HTTP 200; klik ulang tidak mengirim ulang aksi.
