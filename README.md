# Maboyy Digital

**Versi: v16.76** — halaman awal Temp Mail meminta Buat Email terlebih dahulu dan `/tools` menyediakan Hapus Riwayat. Perbaikan flash sale, kuota premium, aktivasi otomatis, pembayaran, dan fitur toko dari versi sebelumnya dipertahankan.

Flash Sale yang waktunya habis disembunyikan dari katalog normal, populer, keranjang, dan paket; tombol lama tidak dapat membuat pembelian baru. Timer tetap disimpan setelah restart. Owner dapat mengaktifkan durasi baru atau memilih **Matikan Flash Sale** untuk mengembalikan produk ke katalog normal. Produk, stok, dan transaksi lama tidak dihapus.

Aktivasi premium mendapat **15 akun per jam**, reset pada awal setiap jam WIB. Kirim Link → Verifikasi → Apply untuk email/flow yang sama dihitung sekali. Pemeriksaan hasil tidak mengurangi kuota akun. **Temp Mail tidak memiliki batas jumlah alamat atau cooldown pembuatan di bot**, dan tidak memakai kuota premium. Atur `TOOLS_PROVIDER_HOURLY_LIMIT=15`; batas server provider tetap mengikuti respons layanan tersebut.

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

Awal `/start`: Belanja dan Rating. Produk normal A–Z: 10 per halaman. Flash Sale aktif tampil khusus menu Flash Sale; setelah habis, produknya tidak masuk ke produk normal. Nomor pilihan mengikuti daftar yang sedang dibuka.
Tombol produk panjang dan pilihan jumlah/MAX dihapus; setiap invoice baru berisi 1 unit.
Daftar produk tetap menyediakan Keranjang, Paket Hemat, dan Riwayat, tanpa Menu Utama/Favorit. Menu Utama hasil akhir kembali ke `/start`.
Pembatalan pesanan menghapus QRIS dan notifikasi pesanan di PM owner; jika Telegram menolak penghapusan, pesan ditandai batal dan tombol dinonaktifkan. Pesan lama yang ID-nya belum tersimpan perlu dihapus manual.
Gunakan `main.py` dan `bot.py` dari paket versi yang sama. `/ping` khusus owner menampilkan uptime proses; isi `HOSTING_PLAN_NAME` dan `HOSTING_PLAN_EXPIRES_AT` di Railway untuk sisa hari paket. Tanggal paket diisi manual; [format dan contoh](VARIABLE_RAILWAY.md#ping-dan-paket-railway-v1671).

Owner: `/tools` → **👑 VIP /tools** → pilih ID → **✅ Jadikan VIP /tools**; **🚫 Cabut VIP /tools** menghentikan akses.
VIP khusus `/tools` di chat pribadi; informasi awal menampilkan pemakaian kuota premium sebenarnya dan jam reset. Aktivasi sekali klik tetap khusus owner.
User VIP: **Magic Link** → email → link dikirim otomatis → salin URL dari inbox ke bot → verifikasi dan Apply Premium otomatis tanpa tombol konfirmasi tambahan.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.
Owner memakai satu tombol **Magic Link / Verifikasi**. Pertahankan endpoint dan API key provider Railway lama.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, varian, harga, dan slot; stok/reservasi tetap tersimpan. Slot yang sudah hilang sebelum upgrade perlu diisi sesuai jumlah sebenarnya.

## Temp Mail dan aktivasi AM owner

`/tools` → **Temp Mail** → **Buat Email** → **Received Mail** → pilih pesan.
Halaman awal dan Refresh tidak memilih email lama atau membuat alamat otomatis. Alamat beserta tombol inbox baru ditampilkan setelah Buat Email, Lanjutkan Pembuatan, atau memilih alamat di Daftar Email. Email yang pernah dibuat tetap tersimpan; pembukaan menu tidak mengganti email aktif atau mengganggu aktivasi yang sedang berjalan. Pratinjau kartu situs inbox dinonaktifkan pada halaman ini.
Saat migrasi, pertahankan nilai `TEMPMAIL_PROVIDER` dan `TOOLS_AUTO_AM_MAIL_PROVIDER` lama; contoh default memakai Grabmail.
**Aktivasi AM Otomatis** → email Grabmail → Magic Link → inbox → verifikasi → Apply Premium, tanpa konfirmasi tambahan.
Jika email belum masuk, bot memeriksa otomatis setiap 30 detik sampai 1 jam; hasil akhir dikirim ke chat owner. Pemantauan tersimpan setelah restart.
Email dan hasil aktivasi memuat link situs inbox yang dapat dibagikan; menu tetap khusus owner, tanpa tombol tambahan.
Grabmail gratis tanpa API key; pesan dihapus setelah 5 hari. [API dan batas layanan](https://grabmail.io/docs/api).
Email Maildrop, Mail.tm, dan Guerrilla tetap didukung tanpa batas 5 alamat atau cooldown lokal. Daftar Email menampilkan 10 alamat per halaman; semua alamat lama tetap tersedia. Mail.tm memakai login, tanpa link inbox publik.
Job aktivasi memakai alamatnya sendiri; klik ulang tidak membuat mailbox baru untuk job yang sama. Sesi token aktivasi otomatis disimpan terenkripsi sampai Apply dimulai atau sesi kedaluwarsa, sehingga restart setelah verifikasi dapat dilanjutkan tanpa verifikasi ulang.
Owner juga cukup mengirim email dan URL Magic Link pada alur manual: bot langsung menjalankan tahap berikutnya, lalu menampilkan hasil Apply. Jika provider sudah memberikan hasil Apply yang eksplisit pada respons verifikasi, hasil tersebut disimpan tanpa Apply kedua. HTTP 202/timeout tetap dilaporkan sebagai menunggu/belum diketahui.
`/tools` → **Hapus Riwayat** → konfirmasi: membersihkan seluruh entri proses selesai dari daftar, filter, dan pencarian, termasuk riwayat terbaru. Tombol juga tersedia di halaman Riwayat. Proses pending, hasil belum diketahui, dan riwayat yang terkait aktivasi berjalan tetap terlihat. Konfirmasi berlaku 5 menit, hanya untuk owner di chat pribadi, dan tidak mencakup entri baru setelah pratinjau. Entri ditandai tersembunyi, bukan menghapus bukti internal yang diperlukan untuk hasil Apply, rating, pemeriksaan duplikasi, statistik, dan kuota. Menghapus riwayat tidak mereset jatah 15 akun/jam atau menghapus email/data toko.
**Bersihkan Log Lama** tetap tersedia untuk menghapus log operasional yang sudah memenuhi aturan retensi 30 hari; inbox, bukti hasil Apply, rating, dan data belanja tetap tersimpan.
Sukses/masa aktif mengikuti respons provider; tanggal kedaluwarsa ditampilkan, tanpa menjanjikan satu tahun baru.
Apply menunggu hingga 30 detik (`TOOLS_PROVIDER_APPLY_TIMEOUT_SECONDS`); request yang hasilnya belum pasti tidak diulang.
Isi saldo: nominal → QRIS/rekening → bukti → verifikasi owner. Caption QRIS tetap berupa invoice; klik berulang memakai invoice aktif. Saat gambar gagal, kontrol invoice tetap tersedia. Fitur lama dipertahankan.

Migrasi schema 188 otomatis menambahkan penanda visibilitas riwayat; seluruh riwayat lama tetap terlihat sampai owner memilih Hapus Riwayat. Catatan kuota akun dan sesi aktivasi terenkripsi dari schema 187 tetap dipertahankan. Jika upgrade langsung dari versi lebih lama, kuota akun jam upgrade dihitung dari histori email lama sekali saja. Pertahankan database, BOT_TOKEN, kunci enkripsi, dan endpoint/API key provider yang sama. Tidak ada dependency atau nama Variable baru. Pengujian memakai database sementara dan simulasi Telegram/API, termasuk transaksi saldo normal; belum diuji dengan credential provider produksi.

Jika versi lama sudah menghapus seluruh penanda/timer Flash Sale suatu produk, kategori lamanya tidak dapat ditentukan dari source ini. Produk tersebut perlu diatur kembali melalui owner. Panduan versi terbaru: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md#perbaikan-v1676).
