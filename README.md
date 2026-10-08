# Maboyy Digital

**Versi: v16.59** — rating toko lebih rapi dan perbaikan alur ulasan.

## Upload GitHub

Ekstrak ZIP lalu upload enam file langsung ke root repository:
`main.py`, `bot.py`, `requirements.txt`, `.env.example`, `README.md`, dan `VARIABLE_RAILWAY.md`.
Perbarui file lama dengan nama yang sama.

Simpan token/API key di Railway Variables/Secrets. Jangan upload `.env`, database,
backup, log, cache Python, atau ZIP sebagai source aplikasi.

## Jalankan di Railway

1. Isi `BOT_TOKEN` dan `ADMIN_ID` sesuai `.env.example`. File contoh tidak otomatis mengisi Railway.
2. Pasang Volume `/data`; isi `DB_PATH=/data/shop.db` dan `BACKUP_DIR=/data/backups`.
3. Gunakan Start Command: `python main.py`.

Konfigurasi lengkap: [VARIABLE_RAILWAY.md](VARIABLE_RAILWAY.md).
Gunakan `main.py` dan `bot.py` dari paket yang sama.

## VIP khusus /tools

Owner: `/tools` → **👑 VIP /tools** → pilih user atau masukkan ID Telegram →
**✅ Jadikan VIP /tools**. Gunakan **🚫 Cabut VIP /tools** untuk menghentikan akses.

VIP hanya berlaku untuk `/tools` di chat pribadi. Panel owner tetap lengkap;
user non-VIP tidak dapat menggunakan fitur tools.

User VIP: **Magic Link** → email → kirim link → salin URL dari inbox ke bot →
**Proses Magic Link** → verifikasi dan Apply Premium otomatis.
**Rating Toko** muncul setelah apply terkonfirmasi sukses, dengan pilihan 1–5 bintang.

Aktifkan provider dan isi URL Send Magic Link, Verify Account, Apply Premium,
serta `TOOLS_PROVIDER_API_KEY` di Railway. API key tidak disertakan dalam `.env.example`.

## Famhead

Owner: `/owner` → **Produk & Stok** → **Atur Produk** → pilih Famhead.
Ubah nama, deskripsi, estimasi, arahan, atau masuk **Atur Varian, Harga & Slot**.
Edit pengaturan dan setup ulang mempertahankan stok serta reservasi yang sudah ada.
Recovery inventory otomatis menjaga slot Famhead/Pre-Order.
Slot yang sudah hilang sebelum upgrade perlu diisi kembali sesuai jumlah sebenarnya.

## Status apply

Hasil mengikuti respons provider. Status pending/belum diketahui tidak mengirim apply ulang.
Pembayaran checkout belum otomatis memicu apply. Apply pada akun asli belum diuji.
