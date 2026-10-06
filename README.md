# Maboyy Produk Digital — Telegram Bot

**Version:** v5.0  
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


## Update v2.1 — Verifikasi Join Channel

Saat user menjalankan `/start`, bot akan mengecek apakah user sudah join channel wajib.

Jika belum join:

```text
🔐 VERIFIKASI CHANNEL

Untuk menggunakan Maboyy Produk Digital,
silakan join channel terlebih dahulu.

[ 📢 Join Channel ]
[ ✅ Saya Sudah Join ]
```

Setelah user menekan `✅ Saya Sudah Join`, bot memeriksa membership menggunakan Telegram API.

Jika sudah join:
- status otomatis terverifikasi
- menu utama langsung dibuka

Jika belum:
- muncul notifikasi untuk join terlebih dahulu
- user dapat mencoba lagi tanpa mengetik command baru

### Railway Variables

Tambahkan:

```env
REQUIRED_CHANNEL_ID=@usernamechannel
REQUIRED_CHANNEL_URL=https://t.me/usernamechannel
REQUIRED_CHANNEL_NAME=Maboyy Digital
```

Untuk channel private, `REQUIRED_CHANNEL_ID` dapat menggunakan numeric chat ID, misalnya:

```env
REQUIRED_CHANNEL_ID=-1001234567890
```

Agar bot dapat mengecek membership dengan stabil, tambahkan bot ke channel sebagai admin.



## Update v2.2 — Minimum Top Up

Minimum top up saldo default sekarang:

```text
Rp5.000
```

Jika user memasukkan nominal di bawah Rp5.000, bot akan menolak transaksi.

Owner juga dapat mengubah minimum top up tanpa edit kode:

```text
/owner
→ 💰 Manajemen Saldo
→ ⚙️ Minimum Top Up
```

Default:

```text
5000
```

Nilai minimum tersimpan di database bot.


## Update v2.3 — Tombol Kembali di Panel Owner

Setiap submenu pada `/owner` sekarang memiliki tombol:

```text
⬅️ Kembali
```

Tombol tersebut akan membawa owner kembali ke panel utama `/owner` tanpa perlu mengetik command lagi.

Submenu yang menggunakan tombol kembali antara lain:

- Tambah Produk
- Tambah Variasi
- Atur Stok
- Atur Harga
- Hapus Produk
- Pesanan
- Verifikasi Pembayaran
- Produk Populer
- Flash Sale
- Voucher
- Pengaturan Pembayaran
- Manajemen Saldo
- Minimum Top Up
- Status Payment Gateway
- Pengaturan QRIS
- Riwayat Saldo


## Update v2.5 — Backup, Persistensi Data & Stok Otomatis

### 1. Data tetap tersimpan saat update/redeploy

Gunakan **Railway Volume** dan mount ke:

```text
/data
```

Kemudian isi Railway Variables:

```env
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
```

Dengan ini database aktif berada di Volume, bukan filesystem sementara deployment.

Yang tetap tersimpan:
- user/wallet
- saldo dan ledger
- top up
- order
- produk dan variasi
- voucher
- QRIS tersimpan
- pengaturan bot
- status announcement
- message ID stok channel

Saat pertama berpindah ke Volume, bot juga mencoba menyalin `shop.db` lama ke lokasi persisten jika file lama masih tersedia.

### 2. Backup otomatis

Default:

```env
BACKUP_INTERVAL_HOURS=48
BACKUP_RETENTION=20
```

Bot membuat snapshot SQLite yang aman menggunakan SQLite backup API.

Backup dapat dikirim otomatis ke:

```env
```


Backup otomatis selalu dikirim langsung ke PM owner berdasarkan `ADMIN_ID`.

Owner juga punya tombol:

```text
/owner
→ 🗄️ Backup Sekarang
```

### 3. Stok terbaru otomatis di channel

Isi:

```env
STOCK_CHANNEL_ID=@usernamechannel
```

Bot membuat satu pesan stok dan selanjutnya **mengedit pesan yang sama**, sehingga channel tidak penuh spam.

Stok otomatis disinkronkan saat:
- produk ditambah
- variasi ditambah
- stok diubah
- harga diubah
- produk dinonaktifkan
- order selesai
- pembayaran berhasil

Owner juga dapat memaksa refresh:

```text
/owner
→ 📢 Sinkron Stok Channel
```

### 5. Izin Channel

Bot harus menjadi admin pada channel update/stok agar bisa:
- mengirim pesan
- mengedit pesan stok

### Railway Variables baru

```env
DB_PATH=/data/shop.db
BACKUP_DIR=/data/backups
BACKUP_INTERVAL_HOURS=48
BACKUP_RETENTION=20

STOCK_CHANNEL_ID=
```

## Perubahan v2.5

Fitur pengumuman update bot otomatis ke channel telah dihapus.

Fitur yang tetap aktif:

- Database persisten melalui Railway Volume
- Backup otomatis
- Backup manual dari panel owner
- Stok terbaru otomatis di channel
- Sinkron stok manual dari panel owner
- Data user, saldo, order, produk, voucher, dan pengaturan tetap tersimpan saat redeploy


## Update v2.6 — Backup Setiap 2 Hari

Backup otomatis sekarang berjalan setiap:

```text
48 jam
```

Railway Variable:

```env
BACKUP_INTERVAL_HOURS=48
```

Backup manual tetap tersedia:

```text
/owner
→ 🗄️ Backup Sekarang
```


## Update v2.7 — Backup Hanya ke PM Owner

Backup otomatis tidak lagi menggunakan channel backup.

Setiap 48 jam file database dikirim langsung ke akun owner berdasarkan:

```env
ADMIN_ID=
```

Variable `BACKUP_CHANNEL_ID` tidak diperlukan lagi.

Backup manual dari:

```text
/owner
→ 🗄️ Backup Sekarang
```

juga dikirim langsung ke PM owner.


## Update v2.8 — Checkout & Pembayaran Lebih Aman

Perbaikan difokuskan pada alur user membeli dan membayar agar tidak mudah terjadi error.

### Checkout aman

- Validasi ulang produk aktif sebelum checkout.
- Validasi ulang stok tepat sebelum order dibuat.
- Proteksi double-tap/double checkout per user.
- QRIS Manual dan QRIS Otomatis menggunakan reservasi stok.
- Stok tersedia = stok fisik dikurangi stok yang sedang direservasi.

### Reservasi stok

Default:

```env
ORDER_RESERVATION_MINUTES=15
```

Selama order QRIS masih pending, stok customer direservasi selama 15 menit.

Jika tidak dibayar sampai batas waktu:

- order menjadi `expired`
- stok reservasi dilepas otomatis
- stok kembali tersedia
- user mendapat notifikasi

### Pembayaran Saldo Kamu

Pembayaran saldo sekarang dilakukan dalam satu transaksi database.

Bot baru menyimpan perubahan jika seluruh langkah berhasil:

1. cek produk
2. cek stok
3. cek saldo
4. buat invoice
5. potong saldo
6. catat ledger
7. kurangi stok
8. tambah jumlah terjual
9. tandai paid/completed

Ini mencegah kasus saldo terpotong tetapi order gagal.

### Proteksi pembayaran ganda

Order yang:
- sudah completed
- expired
- cancelled
- payment_error

tidak akan diproses ulang secara tidak sengaja.

### QRIS Otomatis gagal

Jika pembuatan QR otomatis gagal:

- reservasi stok dilepas
- order ditandai `payment_error`
- customer diarahkan ke QRIS Manual

### File v2.8

Wajib diganti:

- `bot.py`
- `.env.example`
- `README.md`

Tidak berubah:

- `requirements.txt`


## Update v2.9 — Satu Variable Railway

Sekarang seluruh konfigurasi bot dapat disimpan dalam **satu Railway Variable**:

```text
MABOYY_CONFIG
```

Value berupa JSON satu baris.

Contoh:

```json
{"BOT_TOKEN":"TOKEN","ADMIN_ID":"123456789","ADMIN_USERNAME":"username","PAYMENT_NOTE":"QRIS Maboyy Digital","REQUIRED_CHANNEL_ID":"@channel","REQUIRED_CHANNEL_URL":"https://t.me/channel","REQUIRED_CHANNEL_NAME":"Maboyy Digital","DB_PATH":"/data/shop.db","BACKUP_DIR":"/data/backups","BACKUP_INTERVAL_HOURS":48,"BACKUP_RETENTION":20,"ORDER_RESERVATION_MINUTES":15,"STOCK_CHANNEL_ID":"@channel","PUBLIC_BASE_URL":"","SHOPEEPAY_ENABLED":false,"SHOPEEPAY_BASE_URL":"","SHOPEEPAY_CLIENT_ID":"","SHOPEEPAY_CLIENT_SECRET":"","SHOPEEPAY_MERCHANT_ID":"","SHOPEEPAY_STORE_ID":"","SHOPEEPAY_TERMINAL_ID":"","SHOPEEPAY_PRIVATE_KEY":"","SHOPEEPAY_PUBLIC_KEY":""}
```

Saat pindah ke Railway baru:

1. Buat Railway Volume dan mount ke `/data`.
2. Tambahkan satu variable bernama `MABOYY_CONFIG`.
3. Paste value JSON lama.
4. Deploy.

Variable individual lama tetap didukung sebagai fallback, jadi migrasi dapat dilakukan bertahap.

### Keamanan

`MABOYY_CONFIG` mengandung token dan credential rahasia. Jangan upload value aslinya ke GitHub atau kirim ke orang lain.

### File v2.9

Wajib diganti:

- `bot.py`
- `.env.example`
- `README.md`

Tidak berubah:

- `requirements.txt`


## Update v3.0 — Kembali ke Variable Railway Terpisah

Konsep satu variable `MABOYY_CONFIG` dibatalkan.

Konfigurasi kembali menggunakan variable Railway terpisah agar lebih mudah diedit dan dicek.

Fitur lain tetap dipertahankan:
- backup otomatis setiap 48 jam ke PM owner
- database persisten di Railway Volume
- stok otomatis ke channel
- reservasi stok checkout
- proteksi double checkout
- pembayaran saldo atomik
- proteksi pembayaran ganda

Variable utama tetap menggunakan `.env.example` sebagai acuan.


## Update v3.1 — Perbaikan Trigger Backup & Stok Channel

### Backup otomatis

Backup otomatis **tidak lagi dikirim ketika bot start atau redeploy**.

Perilaku sekarang:

1. bot start/redeploy
2. tidak ada backup yang dikirim
3. bot menunggu sesuai `BACKUP_INTERVAL_HOURS`
4. setelah interval penuh, backup dibuat dan dikirim ke PM owner
5. interval diulang kembali

Dengan konfigurasi:

```env
BACKUP_INTERVAL_HOURS=48
```

backup otomatis pertama baru berjalan setelah 48 jam proses bot aktif.

Tombol manual tetap tersedia:

```text
/owner
→ 🗄️ Backup Sekarang
```

### Stok channel

Bot **tidak lagi mengirim atau mengedit pesan stok hanya karena start/redeploy**.

Stok channel hanya disinkronkan ketika memang ada perubahan terkait stok/transaksi, misalnya:

- produk/variasi ditambah
- stok diubah owner
- harga diubah bila tampilan stok memuat harga
- produk dinonaktifkan
- order berhasil dibayar
- reservasi order kadaluarsa dan stok kembali tersedia
- owner menekan `📢 Sinkron Stok Channel`

Dengan demikian deploy/update kode tanpa perubahan stok tidak lagi memunculkan update stok baru di channel.


## Update v3.2 — Pengiriman Akun Premium Otomatis & Atur Stok Lebih Mudah

### Perbaikan utama

Sebelumnya pembayaran dapat berstatus selesai tetapi bot hanya mengurangi stok angka dan belum memiliki data akun premium yang bisa dikirim.

Sekarang bot memiliki **inventory akun premium per variasi**.

Owner mengisi stok akun melalui:

```text
/owner
→ 📦 Atur Stok
→ pilih produk
→ pilih variasi
→ ➕ Tambah Akun
```

Tidak perlu mengetik ID produk atau ID variasi.

Format pengisian:

```text
email1@gmail.com | password1
email2@gmail.com | password2
email3@gmail.com | password3
```

Satu baris = satu akun / satu stok.

### Setelah pembayaran berhasil

Bot akan:

1. memastikan pembayaran tercatat satu kali
2. mengambil akun yang belum pernah terjual
3. menandai akun sebagai sold
4. mengurangi stok
5. menyimpan data akun pada order
6. mengirim akun premium langsung ke user
7. memperbarui stok channel

### Jika akun belum tersedia

Pembayaran tidak hilang dan user tidak perlu membayar ulang.

Status menjadi:

```text
paid_pending_delivery
```

User mendapat informasi bahwa akun sedang disiapkan, dan owner mendapat peringatan untuk menambah stok akun.

Setelah owner menambah akun, bot otomatis mencoba memenuhi pesanan yang sudah dibayar.

### Menu Atur Stok

Alur baru:

```text
📦 Atur Stok
→ pilih Produk
→ pilih Variasi
→ ➕ Tambah Akun
   atau
→ 🧮 Set Stok Angka
   atau
→ 📤 Kirim Pending
```

Untuk produk akun premium, `➕ Tambah Akun` adalah metode yang direkomendasikan.


## Update v3.3 — Stok Channel Hanya Diatur Owner

Sinkronisasi stok otomatis ke channel telah dihapus.

Bot tidak lagi mengedit pesan stok channel ketika:

- produk ditambah
- variasi ditambah
- stok berubah
- harga berubah
- pembayaran berhasil
- order selesai
- reservasi stok kadaluarsa
- stok akun premium ditambahkan
- bot start/redeploy

Sekarang informasi stok di channel hanya berubah ketika owner menjalankan:

```text
/owner
→ 📢 Sinkron Stok Channel
```

Dengan begitu owner memegang kontrol penuh kapan informasi stok di channel diperbarui.

Variable berikut tetap digunakan:

```env
STOCK_CHANNEL_ID=
```

Variable tersebut hanya menentukan channel tujuan saat owner menekan tombol sinkron manual.


## Update v3.4 — Audit Stabilitas Pembelian & Pengiriman

Audit ini memperketat alur pembelian dari checkout sampai akun diterima user.

Perbaikan utama:

- migrasi database fulfillment untuk database lama
- akun dialokasikan ke invoice sebelum dikirim
- status `delivered` baru disimpan setelah Telegram berhasil mengirim
- jika pengiriman gagal, akun yang sama tetap terkunci pada invoice dan dapat dicoba ulang
- tombol `📩 Kirim Ulang Akun Terakhir` di Pesanan Saya
- proteksi double-tap checkout Saldo, QRIS Manual, dan QRIS Otomatis
- pembayaran valid yang datang setelah order expired tetap dicatat
- jika stok sudah terpakai, order menjadi `paid_pending_delivery`; user tidak perlu membayar ulang
- parsing nominal callback menggunakan Decimal
- stok akun mengikuti credential yang benar-benar tersedia
- Set Stok Angka tidak digunakan pada alur utama untuk mencegah stok tanpa akun
- update stok channel tetap hanya manual oleh owner

Alur fulfillment:

```text
Pembayaran valid
→ akun dialokasikan
→ data akun disimpan di order
→ Telegram mengirim
→ berhasil
→ akun sold
→ order completed
```

Jika Telegram gagal:

```text
send_failed
→ akun tetap milik invoice
→ retry
→ akun yang sama dikirim ulang
```

Tidak ada Railway Variable baru.


## Update v3.5 — Hapus Produk Lebih Mudah

Owner tidak perlu lagi mengetik ID produk.

Alur baru:

```text
/owner
→ 🗑️ Hapus Produk
→ pilih Produk
→ lihat ringkasan
→ ✅ Ya, Hapus Produk
```

Sebelum penghapusan, bot menampilkan:
- nama produk
- jumlah variasi aktif
- stok tersedia
- jumlah order aktif/pending
- jumlah akun inventory yang masih tersedia/teralokasi

### Proteksi

Penghapusan menggunakan soft delete:
- produk hilang dari toko
- variasi produk ikut nonaktif
- riwayat order lama tetap tersimpan
- database tidak dihapus secara permanen

Jika masih ada order `pending` atau `paid_pending_delivery`, bot menolak penghapusan sampai order tersebut diselesaikan.


## Update v3.6 — Recovery & Kontrol Owner

Versi ini menambahkan alat recovery agar transaksi yang nyangkut lebih mudah ditangani tanpa mengubah pembayaran user.

### 🩺 Cek Sistem

Menu:

```text
/owner
→ 🩺 Cek Sistem
```

Menampilkan:
- order pending
- paid pending delivery
- send failed
- akun allocated
- akun available
- jumlah produk/variasi aktif
- stock mismatch
- status database
- backup terakhir

### ♻️ Recovery Order

Menu:

```text
/owner
→ ♻️ Recovery Order
```

Bot mencoba kembali semua order yang:
- sudah paid
- belum delivered
- send_failed
- paid_pending_delivery

Recovery tidak membuat invoice baru dan tidak melakukan charge baru.

Saat bot redeploy, ada satu recovery pass otomatis setelah startup untuk mencoba pengiriman order yang sebelumnya nyangkut.

### 📨 Kirim Ulang Akun dari Owner

Menu:

```text
/owner
→ 📨 Kirim Ulang Akun
→ pilih invoice
```

Bot mengirim ulang credential yang tersimpan di invoice yang sama.
Tidak mengambil akun baru dan tidak mengurangi stok.

### ❌ Batalkan Order

Menu:

```text
/owner
→ ❌ Batalkan Order
```

Hanya order pending yang belum dibayar yang bisa dibatalkan.

Saat dibatalkan:
- status menjadi cancelled
- reservasi stok dilepas
- user mendapat notifikasi

Order yang sudah `paid` tidak dapat dibatalkan dari menu ini.

### Railway

Tidak ada Railway Variable baru pada v3.6.


## Update v3.7 — Restock Alert ke Semua User Terverifikasi

Restock tidak lagi hanya mengandalkan channel.

Bot sekarang menyimpan daftar user yang berhasil melewati verifikasi channel.

User dicatat sebagai verified ketika:
- `/start` dan pengecekan channel berhasil
- menekan `✅ Saya Sudah Join` dan lolos verifikasi
- membuka kembali Menu Utama dan masih lolos pengecekan

### Restock otomatis

Saat owner menambah akun melalui:

```text
/owner
→ 📦 Atur Stok
→ pilih produk
→ pilih variasi
→ ➕ Tambah Akun
```

Jika stok berubah dari:

```text
0 → tersedia
```

bot otomatis mengirim **Restock Alert melalui PM** ke semua user terverifikasi.

Isi alert:
- nama produk
- nama variasi
- stok terbaru
- harga
- tombol `🛒 Lihat Produk`

Alert tidak otomatis dikirim jika stok sebelumnya masih tersedia, supaya user tidak menerima spam setiap kali owner menambah sedikit stok.

### Broadcast manual

Pada detail stok owner tersedia tombol:

```text
📣 Broadcast Restock
```

Owner dapat mengirim ulang informasi stok kapan saja jika memang diperlukan.

### Proteksi broadcast

- owner tidak ikut menerima alert customer
- user yang memblokir bot ditandai nonaktif
- Telegram flood-limit ditangani dengan retry
- hasil broadcast dilaporkan ke PM owner
- log jumlah terkirim/gagal disimpan di database

### Channel stok

Fitur ini tidak mengaktifkan kembali update stok otomatis ke channel.

`📢 Sinkron Stok Channel` tetap hanya berjalan jika owner menekan tombol secara manual.

Tidak ada Railway Variable baru.


## Update v3.8 — Catatan Sebelum Pembayaran

User sekarang dapat mengisi catatan sebelum memilih metode pembayaran.

Alur checkout:

```text
Pilih produk
→ pilih variasi
→ pilih jumlah
→ Konfirmasi
→ 📝 Isi Catatan / ⏭️ Lewati Catatan
→ pilih metode pembayaran
```

Contoh catatan:

```text
Email tujuan: nama@email.com
Profil: Anak
Request: jangan ubah password
```

Catatan:
- maksimal 500 karakter
- opsional, user dapat memilih Lewati Catatan
- tersimpan di order
- ditampilkan pada pembayaran
- terlihat oleh owner
- tetap tersimpan pada riwayat pesanan

Tidak ada Railway Variable baru.


## Update v3.9 — Tampilan Variasi, Harga & Stok

Halaman detail produk sekarang menampilkan seluruh variasi secara langsung.

Contoh:

```text
📦 VARIASI • HARGA • STOK

1. Standard
   💰 Harga: Rp25.000
   ✅ Stok: 12

2. Premium
   💰 Harga: Rp40.000
   ❌ Stok: 0
```

Tombol variasi juga menampilkan:

```text
🛒 Standard • Rp25.000 • Stok 12
❌ Premium • Rp40.000 • Habis
```

Dengan begitu user tidak perlu membuka variasi satu per satu hanya untuk melihat harga dan stok.

Tidak ada Railway Variable baru.


## Update v4.0 — Tombol Variasi Lebih Ringkas

Tombol variasi sekarang hanya menampilkan:

```text
Standard (12)
Premium (0)
```

Harga tetap tampil di isi detail produk pada bagian:

```text
VARIASI • HARGA • STOK
```

Jadi tombol lebih bersih, tetapi user tetap bisa melihat harga dan stok lengkap di pesan produk.


## Update v4.1 — Nama Tombol Variasi Bisa Diubah

Owner sekarang dapat mengubah nama yang tampil pada tombol variasi tanpa mengubah stok.

Menu:

```text
/owner
→ 🏷️ Nama Tombol Variasi
→ pilih Produk
→ pilih Variasi
→ kirim Nama Tombol Baru
```

Contoh:

```text
Nama variasi asli: Standard
Nama tombol: 1 Bulan
Stok tersedia: 12
```

Tombol user tampil:

```text
1 Bulan (12)
```

Angka `(12)` berasal dari stok tersedia dan diperbarui otomatis.

Kirim:

```text
RESET
```

untuk mengembalikan nama tombol ke nama variasi asli.

Tidak ada Railway Variable baru.


## Update v4.2 — Menu Tombol Bawah Telegram

Saat user menjalankan `/start`, bot sekarang menampilkan menu permanen di bagian bawah Telegram.

Tombol:

```text
🏷️ List Produk   🎁 Voucher   📁 Laporan Stok
🔥 Produk Populer   ⚡ Flash Sale
🧾 Pesanan Saya   💰 Saldo Kamu
❓ Cara Order   💬 Hubungi Owner
```

Menu menggunakan Telegram Reply Keyboard:
- tetap terlihat saat user chat dengan bot
- dapat diperkecil/dibuka kembali lewat tombol Menu Telegram
- setiap tombol langsung menjalankan fungsi terkait
- inline button lama tetap dipertahankan untuk navigasi di dalam menu

Tidak ada Railway Variable baru.


## Update v4.3 — Tombol Jumlah Stok & Isi Saldo

### Tombol jumlah beli

Saat user membuka variasi produk, jumlah pembelian sekarang dapat dipilih langsung melalui tombol angka.

Contoh jika stok 12:

```text
1  2  3  4  5
6  7  8  9  10
11 12
```

Jumlah tombol otomatis mengikuti stok yang tersedia.

Jika stok lebih dari 20:
- tombol cepat menampilkan 1–20
- tersedia tombol `📦 MAX <stok>`

Masih tersedia tombol `➖` dan `➕` untuk penyesuaian.

User tidak dapat memilih jumlah melebihi stok sebenarnya.

### Isi Saldo

Menu Saldo Kamu sekarang memiliki alur isi saldo yang lebih aman:

```text
Saldo Kamu
→ ➕ Isi Saldo
→ pilih nominal cepat / + / - / custom
→ Konfirmasi
→ Buat Invoice QRIS
```

Nominal cepat:
- Rp5.000
- Rp10.000
- Rp20.000
- Rp50.000
- Rp100.000
- Rp200.000

Nominal yang lebih kecil dari minimum top up otomatis tidak ditampilkan.

Fitur tambahan:
- tombol tambah/kurang Rp5.000
- nominal custom
- konfirmasi nominal sebelum invoice
- menampilkan perkiraan saldo setelah top up
- anti double-click invoice top up selama 30 detik
- kode unik tetap digunakan untuk QRIS manual
- owner tetap memverifikasi top up sebelum saldo masuk

Tidak ada Railway Variable baru.


## Update v4.4 — Tombol Nomor Produk di Menu Bawah

Menu bawah Telegram sekarang mengikuti konsep video contoh.

Contoh jika ada 21 produk aktif:

```text
🏷️ List Produk   🎁 Voucher   📁 Laporan Stok

1   2   3   4   5
6   7   8   9   10
11  12  13  14  15
16  17  18  19  20
21

💰 Isi Saldo     ❓ Cara Order
🧾 Pesanan Saya  💬 Hubungi Owner
```

### Cara kerja nomor produk

- angka dibuat otomatis berdasarkan jumlah produk aktif
- maksimal 25 shortcut produk pada keyboard bawah
- urutan angka sama dengan urutan di `List Produk`
- menekan angka langsung membuka detail produk
- jika produk dihapus/dinonaktifkan, menu akan menyesuaikan saat keyboard diperbarui

Nomor hanya menjadi shortcut. Nama produk, variasi, harga, dan stok tetap berasal dari database Maboyy Digital.

### Isi Saldo

Tombol `💰 Isi Saldo` di menu bawah langsung membuka pilihan nominal Isi Saldo v4.3.

Tidak ada Railway Variable baru.


## Update v4.6 — Rollback Integrasi Xoftware

Integrasi QRIS otomatis Xoftware dari v4.5 dibatalkan.

Bot dikembalikan ke basis fitur v4.4:
- menu tombol bawah Telegram
- nomor produk otomatis
- tombol jumlah beli berdasarkan stok
- fitur Isi Saldo yang sudah ditingkatkan
- QRIS manual
- integrasi payment gateway lama tetap dipertahankan sesuai konfigurasi sebelumnya

Tidak ada konfigurasi Xoftware di versi ini.

Tidak ada Railway Variable Xoftware yang diperlukan.


## Update v4.7 — Professional Operations Pack

### 🛡️ Anti-Fraud & Anti-Abuse
- batas invoice pending per user
- cooldown checkout
- risk log
- block/unblock user dari `/owner`
- transaksi user yang diblokir ditolak

### 📊 Dashboard Owner
Dashboard statistik sekarang menampilkan:
- order dan omzet hari ini
- omzet keseluruhan
- pending bayar
- paid pending delivery
- stok akun siap jual
- user terverifikasi
- total saldo user
- produk terlaris
- jumlah ulasan

### 🔔 Alert Stok Menipis
Owner dapat menentukan threshold dari:
`/owner → 🔔 Alert Stok`

Saat stok setelah penjualan mencapai threshold, owner mendapat PM otomatis.

### 🧾 Invoice Profesional
Struktur invoice helper baru menyimpan subtotal, voucher, total, metode dan status secara konsisten.

### ⭐ Rating & Ulasan
Setelah akun berhasil dikirim:
- user otomatis mendapat tombol 1–5 ⭐
- satu order hanya dapat dinilai satu kali
- rating produk dihitung ulang otomatis
- rating tampil pada detail produk
- owner dapat melihat ulasan terbaru

### 🎟️ Voucher Lanjutan
Voucher mendukung:
- minimum transaksi
- maksimum diskon
- kuota global
- limit per user
- masa aktif
- produk tertentu
- variasi tertentu
- pelanggan baru
- pemakaian voucher langsung di checkout

Format owner:
`KODE | DISKON | MIN | MAX | KUOTA | PERUSER | HARI | PRODUCT_ID | VARIANT_ID | NEW`

### 🏅 Loyalty
Level pelanggan:
- Bronze
- Silver
- Gold
- VIP

Level dihitung dari total order selesai dan tampil di Saldo Kamu.

### 📚 Riwayat Stok
Restock dan akun terjual dicatat di log inventory.
Owner dapat membuka `/owner → 📚 Riwayat Stok`.

### ♻️ Recovery
Mekanisme fulfillment lama tetap dipertahankan:
- allocated credential tidak diberikan ke user lain
- send_failed dapat diretry
- paid_pending_delivery tetap aman
- recovery owner tetap tersedia

### 💰 Isi Saldo lebih aman
- topup hanya dapat diverifikasi sekali
- metadata verifikasi disimpan
- owner dapat menolak topup dengan alasan
- user menerima alasan penolakan
- saldo tidak berubah saat topup ditolak

Tidak ada Railway Variable baru.


## Update v4.8 — Owner Settings Berbasis Tombol

Pengaturan owner dibuat lebih mudah dan tidak lagi mengandalkan format panjang seperti:

`KODE | DISKON | MIN | MAX | ...`

Perubahan:
- pembuatan voucher menggunakan wizard tombol langkah demi langkah
- pilihan diskon melalui tombol
- minimum transaksi melalui tombol
- kuota voucher melalui tombol
- limit per user melalui tombol
- masa aktif melalui tombol
- target pelanggan melalui tombol
- verifikasi top up menggunakan tombol invoice
- penolakan top up menggunakan tombol invoice + tombol alasan
- block/unblock user anti-fraud menggunakan tombol user

Input teks hanya dipakai saat memang membutuhkan nilai bebas seperti:
- nama/kode voucher
- nominal custom

Tidak ada Railway Variable baru.


## Update v4.9 — Stability, Operations & Growth Pack

Prinsip utama v4.9:
- tampilan menu awal user tetap sama seperti v4.8
- tampilan `Pesanan Saya` tetap sama seperti v4.8
- alur order langsung tetap menjadi default
- fitur baru ditempatkan di submenu, owner panel, atau background task

### Fitur baru
- Smart Recovery berkala setiap 5 menit
- sinkronisasi stok otomatis dari inventory truth
- System Self-Test owner
- Maintenance Mode
- Broadcast tersegmentasi
- Segmentasi user
- Cashback otomatis yang bisa diatur owner
- Laporan harian owner
- Search produk
- Keranjang
- Checkout semua keranjang dengan Saldo Kamu
- Produk favorit
- Beli lagi order terakhir
- Detail invoice terakhir
- Paket / Bundle
- Bundle dapat dimasukkan ke keranjang
- Laporan harian memakai zona waktu Asia/Jakarta

### Catatan keamanan
Checkout keranjang membuat invoice terpisah untuk setiap item supaya mekanisme fulfillment, recovery, dan inventory lama tetap aman.

Tidak ada Railway Variable baru.


## Update v5.0 — Navigation Reliability Fix

Perbaikan fokus pada seluruh tombol kembali dan callback navigation.

Perubahan:
- menambahkan handler `owner:panel` yang sebelumnya belum ada
- seluruh tombol `⬅️ Kembali` diaudit
- navigasi dari text message dan media/caption dibuat lebih aman
- tombol lama dari pesan versi sebelumnya mendapat fallback agar tidak diam
- menu awal user tetap sama
- `Pesanan Saya` tetap sama
- alur order tetap sama

Tidak ada Railway Variable baru.
