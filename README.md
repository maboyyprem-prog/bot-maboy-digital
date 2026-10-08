# Maboyy Digital

**Versi: v16.66** — Aktivasi AM Pro 1 tahun memakai Maildrop otomatis.

## Upload GitHub

Upload enam file dari ZIP langsung ke root GitHub: `main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.

Simpan token/API key di Railway. Jangan upload `.env`, database, backup, log, cache, atau ZIP sebagai source.

## Jalankan di Railway

1. Isi `BOT_TOKEN` dan `ADMIN_ID` sesuai `.env.example`. File contoh tidak otomatis mengisi Railway.
2. Pasang Volume `/data`; isi `DB_PATH=/data/shop.db` dan `BACKUP_DIR=/data/backups`.
3. Gunakan Start Command: `python main.py`.

Produk: 10 per halaman dengan tombol langsung. Riwayat: menu awal/selesai → invoice → detail.
Konfigurasi: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md); gunakan `main.py` dan `bot.py` dari paket yang sama.

## VIP khusus /tools

Owner: `/tools` → **👑 VIP /tools** → pilih ID → **✅ Jadikan VIP /tools**; **🚫 Cabut VIP /tools** menghentikan akses.

VIP khusus `/tools` di chat pribadi; informasi awal menampilkan teks statis **0/15 akun/jam**. Aktivasi sekali klik tetap khusus owner.

User VIP: **Magic Link** → email → kirim link → salin URL dari inbox ke bot →
**Proses Magic Link** → verifikasi dan Apply Premium otomatis.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.

Owner memakai satu tombol **Magic Link / Verifikasi**. Isi endpoint dan API key provider di Railway.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, varian, harga, dan slot; stok/reservasi tetap tersimpan.
Recovery menjaga slot Famhead/Pre-Order; slot yang sudah hilang sebelum upgrade perlu diisi sesuai jumlah sebenarnya.

## Temp Mail dan aktivasi AM owner

`/tools` → **Temp Mail** → **Buat Email** → **Received Mail** → pilih pesan.
Email baru: [Maildrop](https://docs.maildrop.cc/) gratis; `TEMPMAIL_PROVIDER=maildrop`. Email Mail.tm lama tetap didukung; batas 5 email per provider.
**Aktivasi AM Otomatis** → email Maildrop → Magic Link → baca inbox → verifikasi → Apply Premium; tetap memakai Maildrop apa pun pengaturan Temp Mail manual.
Email dan hasil aktivasi memuat link situs inbox yang dapat dibagikan; menu tetap khusus owner, tanpa tombol tambahan.
Inbox publik; pesan dapat dihapus setelah 24 jam tanpa email baru. Pengiriman pertama kadang tertunda 15 menit–1 jam.
**Bersihkan Log Lama** meminta konfirmasi; inbox, hasil apply, rating, dan data belanja tetap tersimpan.

## Status apply

Sukses mengikuti hasil apply provider; paket/masa aktif mengikuti data provider, termasuk konfirmasi 1 tahun.
**Lanjutkan** memakai email Temp Mail yang sama dan memeriksa status tanpa mengulang apply. Pengujian memakai simulasi; apply asli belum diuji.
