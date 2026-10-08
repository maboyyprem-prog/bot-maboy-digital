# Maboyy Digital

**Versi: v16.63** — Aktivasi AM otomatis khusus owner; informasi VIP lebih jelas.

## Upload GitHub

Ekstrak ZIP lalu upload enam file langsung ke root repository:
`main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.
Perbarui file lama dengan nama yang sama.

Simpan token/API key di Railway. Jangan upload `.env`, database, backup, log, cache, atau ZIP sebagai source.

## Jalankan di Railway

1. Isi `BOT_TOKEN` dan `ADMIN_ID` sesuai `.env.example`. File contoh tidak otomatis mengisi Railway.
2. Pasang Volume `/data`; isi `DB_PATH=/data/shop.db` dan `BACKUP_DIR=/data/backups`.
3. Gunakan Start Command: `python main.py`.

Riwayat: menu awal/selesai → pilih invoice → detail; kirim ulang akun dari detail pesanan selesai.
Konfigurasi: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md); gunakan `main.py` dan `bot.py` dari paket yang sama.
## VIP khusus /tools

Owner: `/tools` → **👑 VIP /tools** → pilih ID → **✅ Jadikan VIP /tools**; **🚫 Cabut VIP /tools** menghentikan akses.

VIP khusus `/tools` di chat pribadi; informasi awal menampilkan teks statis **0/15 akun/jam**. Aktivasi sekali klik tetap khusus owner.

User VIP: **Magic Link** → email → kirim link → salin URL dari inbox ke bot →
**Proses Magic Link** → verifikasi dan Apply Premium otomatis.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.

Isi URL Send Magic Link, Verify Account, Apply Premium dan `TOOLS_PROVIDER_API_KEY` di Railway.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, varian, harga, dan slot; stok/reservasi tetap tersimpan.
Recovery menjaga slot Famhead/Pre-Order; slot yang sudah hilang sebelum upgrade perlu diisi sesuai jumlah sebenarnya.

## Temp Mail dan aktivasi AM owner

`/tools` → **Temp Mail** → **Buat Email** → **Received Mail** → pilih pesan.
API [Mail.tm](https://docs.mail.tm/) gratis tanpa API key; akun tersimpan terenkripsi.
**Aktivasi AM Otomatis** → buat email → kirim Magic Link → baca inbox → verifikasi → Apply Premium.
Hasil final berisi email dan **Received Mail**/tautan inbox Telegram untuk membaca pesan akun itu.
**Bersihkan Log Lama** meminta konfirmasi; inbox, hasil apply, rating, dan data belanja tetap tersimpan.

## Status apply

Sukses mengikuti hasil apply provider; paket/masa aktif mengikuti data provider, termasuk konfirmasi 1 tahun.
Pending membaca status tanpa mengirim apply ulang. Checkout tetap terpisah; apply akun asli belum diuji.
