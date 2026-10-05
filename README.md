# Maboyy Produk Digital — Telegram Bot

**Version:** v2.0  
**Footer:** Aplikasi Premium • Since 2020

## Command

Tetap hanya:

- `/start`
- `/owner`
- `/ping`

## Update v2.0 — Saldo Kamu

### Fitur User

- 💰 Saldo Kamu
- ➕ Top Up Saldo
- 📑 Riwayat Saldo
- 🛒 Bayar langsung menggunakan Saldo Kamu
- Saldo otomatis berkurang saat pembelian berhasil
- Refund otomatis ke saldo jika proses order gagal
- Top up melalui QRIS manual + kode unik

### Fitur Owner

`/owner → 💰 Manajemen Saldo`

Tersedia:

- Tambah saldo user
- Kurangi saldo user
- Verifikasi top up
- Riwayat transaksi saldo
- Total saldo tersimpan
- Jumlah top up pending

Semua perubahan saldo dicatat dalam ledger sehingga lebih mudah diaudit.

## Pembayaran

Tampilan customer menggunakan nama generik:

- 💰 Saldo Kamu
- 🟡 QRIS Manual
- ⚡ QRIS Otomatis

Nama provider/payment gateway tidak ditampilkan ke customer.

Integrasi otomatis tetap dipersiapkan di backend dan dapat diaktifkan setelah credential resmi tersedia.

## Keamanan Saldo

- Saldo tidak boleh minus
- Setiap transaksi mempunyai reference
- Ledger transaksi mencegah transaksi yang sama diproses dua kali
- Top up yang sudah diverifikasi tidak dapat dikreditkan dua kali
- Pembelian menggunakan saldo langsung ditandai paid jika berhasil
- Jika fulfillment gagal, saldo direfund otomatis

## Railway Variables

Variable lama tetap:

```env
BOT_TOKEN=
ADMIN_ID=
ADMIN_USERNAME=
PAYMENT_NOTE=QRIS Maboyy Digital
```

Variable Payment Gateway otomatis tetap opsional dan tidak perlu diaktifkan sekarang.

## Start Command

```bash
python bot.py
```

## File v2.0

File yang berubah dan perlu diganti di GitHub:

- bot.py
- README.md

File yang tidak berubah dari v1.8:

- requirements.txt
- .env.example

Aplikasi Premium • Since 2020
