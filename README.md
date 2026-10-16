# MaboyyDigital v17.17

Paket ringkas: **15 file**, langsung di root ZIP. Upload seluruh isinya ke root repository GitHub.

## VIP /tools Rp20.000 per bulan

User membuka **/tools → VIP → Bayar Saldo atau QRIS Otomatis**, lalu konfirmasi.
Saldo memakai wallet bot existing; QRIS memakai gateway existing dan biaya akhirnya
terlihat sebelum dibayar. VIP aktif setelah pembayaran terverifikasi, mendapat
invoice gambar sekali, lalu mengikuti rating pembelian existing.

Masa aktif **satu bulan kalender dalam WIB**. Setelah habis, akses otomatis kembali
normal, termasuk ketika user sedang menjalankan form /tools. Tidak ada perpanjangan
atau potongan saldo otomatis. Membeli perpanjangan sebelum habis menambah satu bulan
dari tanggal berakhir; membeli setelah habis dihitung dari waktu aktivasi baru.
Akses permanen yang diberikan owner sebelumnya tetap mengikuti pengaturan owner.

Schema **202** menambah riwayat pembelian VIP dan masa aktif secara additive.
Harga tetap Rp20.000; tidak ada Variables atau file runtime baru. Pertahankan
database, Volume, konfigurasi /tools, serta gateway existing saat redeploy.

## Setelah QRIS berhasil dibayar

QRIS otomatis diganti menjadi **satu invoice gambar pembayaran berhasil** pada
pesan yang sama. Salinan QRIS lain dibersihkan. Notifikasi teks pembayaran sukses
yang berulang dihapus khusus QRIS Otomatis; pengiriman produk tetap berjalan.
ID pesan dan antrean invoice tersimpan agar webhook berulang/restart tidak
menggandakan invoice. Jika hasil kirim gambar baru tidak pasti, bot tidak mengirim
ulang otomatis; owner dapat memeriksanya di rincian Riwayat Transaksi.

Schema **201** pada rilis sebelumnya menambah tabel pencatatan pesan QRIS; data wallet/invoice lama
dipertahankan. Tidak ada Variables baru. Untuk QRIS checkout dari versi lama yang
belum menyimpan ID pesan, tekan **Cek Status** pada pesan tersebut satu kali setelah
update agar bot mengenali dan membersihkannya. Pesan sukses lama yang sebelumnya
tidak dicatat tidak dapat dihapus otomatis dari riwayat Telegram.

## QRIS langsung bersama invoice

Saat user memilih **⚡ QRIS Otomatis** untuk isi saldo atau checkout, gambar QRIS
langsung dikirim bersama nomor invoice, nominal, biaya, total dan waktu WIB.
Tombol **Tampilkan QRIS** dihapus. **Cek Status** juga menampilkan kembali QRIS
invoice yang sama selama masih menunggu pembayaran, termasuk setelah pemulihan
invoice tertunda atau kegagalan pengiriman gambar. Tidak membuat tagihan baru.
Invoice yang sudah dibayar menampilkan invoice sukses yang sama tanpa kirim
ulang; invoice kedaluwarsa atau dibatalkan menampilkan status.

## Pemeriksaan gateway untuk akun baru

Gunakan **/owner → Pengaturan Pembayaran → QRIS Otomatis → Aktifkan KlikQRIS**.
Aktivasi gateway biasa mengizinkan pembuatan invoice pertama dengan konfigurasi
yang sudah diisi. Tidak perlu riwayat, ID uji atau transaksi percobaan. Status API
awal **Menunggu invoice pertama**; API dinyatakan terverifikasi setelah respons
pembuatan QRIS nyata lolos pemeriksaan referensi, nominal dan signature.

User memilih /start → Isi Saldo → ⚡ QRIS Otomatis. Saldo masuk setelah pembayaran
invoice asli dan nominalnya diverifikasi melalui API; membuat QRIS tidak menambah
saldo. Cek Koneksi memakai invoice nyata yang tersimpan atau riwayat bila tersedia.
Riwayat HTTP 404 tidak menghalangi aktivasi. Tidak ada Variables baru.

## Perbaikan aktivasi KlikQRIS

Di Railway, kolom **Name** diisi `KLIKQRIS_WEBHOOK_URL`; kolom **Value** cukup URL:
`https://DOMAIN_BOT_ANDA/webhooks/klikqris`. Jangan menempelkan `NAMA_VARIABEL=`
di kolom Value. Format tempelan seperti pada laporan sebelumnya kini dikenali,
termasuk kutip pembungkus. API Key/Merchant ID tetap tidak ditampilkan di Telegram.

Buka **/owner → Pengaturan Pembayaran → QRIS Otomatis → Aktifkan KlikQRIS**.
API gateway dibuktikan melalui invoice nyata. Aktivasi tidak membuat tagihan percobaan.
Error konfigurasi menyebut variabel yang perlu diperbaiki, dan kegagalan API
tetap terlihat di panel. Tidak ada Variables atau file runtime baru; schema 201 sebelumnya
menambahkan pencatatan pesan QRIS. Mode MY PG tetap memerlukan merchant terhubung
yang terverifikasi.

## Prioritas rating pembelian

Setelah produk dikirim, SMS OTP diterima, Sosmed selesai, atau aktivasi /tools
berhasil, user memilih **1–5 bintang** sebelum membuka fitur lain atau membeli lagi.
Rating rendah tetap diterima; komentar tertulis opsional. Jika ada beberapa transaksi
yang selesai, rating ditampilkan bergantian. Antrean tersimpan setelah restart;
transaksi lama yang sudah selesai sebelum update tidak dipaksa rating ulang.

Status pembayaran, bukti bayar invoice berjalan, kode OTP/resend/selesai, pembatalan,
riwayat pesanan dan bantuan tetap dapat diakses. Webhook, polling, kredit saldo,
refund dan pengiriman berjalan tanpa menunggu rating. Order pending/gagal/partial
dan isi saldo tidak memicu kewajiban rating. Panel administrasi owner tetap bisa
digunakan; tampilan owner dibatasi ke chat privat. User tidak mendapat tombol admin.

Menu rating memakai pesan yang sama saat user mencoba berpindah fitur. Setelah
rating tersimpan, menu terbuka kembali. Tidak ada file runtime atau Variables baru
untuk fitur rating; gunakan seluruh 15 file rilis v17.17 yang konsisten.

## Jalankan

Python 3.12. Install `pip install -r requirements.txt`, lalu `python main.py`.
Railway: Start Command `python main.py`, health `/health`, satu replica.
Pasang Volume `/data`; Variables `DB_PATH=/data/shop.db`, `BACKUP_DIR=/data/backups`.
Pertahankan database, token, konfigurasi pembayaran, dan kunci enkripsi existing.
Hentikan poller lama sebelum menggunakan token yang sama pada Railway baru.

## Command

`/start` · `/otp` · `/sosmed` · `/tools` · `/owner` · `/ping`.
`/sosmed` membuka panel owner untuk owner dan toko pembeli untuk user.
Owner bisa memilih **Menu Pembeli** untuk belanja memakai wallet pribadinya.
Saldo user dipakai bersama oleh toko, OTP, dan Sosmed.

Pembelian baru **/otp dan /sosmed hanya memakai saldo bot**. OTP memakai
**Buy Saldo**, Sosmed memakai **Bayar Saldo**. Jika saldo kurang, pilih
**Isi Saldo** melalui alur deposit existing, lalu pilih layanan kembali.
QRIS/payment gateway tetap tersedia untuk isi saldo dan checkout produk existing.
Invoice QRIS OTP yang sudah dibuat sebelum pembaruan tetap direkonsiliasi dengan
aturan lama; tombol QRIS lama tidak bisa membuat invoice pembelian baru.

Sosmed: transaksi **hold/pending tanpa ID provider** ikut tampil pada Pesanan dan
Riwayat, dengan ID transaksi `T-`, nominal ditahan, waktu WIB dan tombol detail.
Penolakan pembelian definitif masuk Riwayat dengan saldo yang sudah dilepas.
Timeout/status belum pasti tetap direkonsiliasi; bot tidak membeli ulang otomatis.

Owner: buka **/sosmed → Semua Pesanan atau Rekonsiliasi → pilih transaksi T- →
Batalkan & Refund Saldo → Konfirmasi**. Nominal ditahan dikembalikan penuh ke wallet
user dengan ledger atomik; double click tidak menambah saldo dua kali. Status menjadi
**Dibatalkan**, masuk Riwayat, dan bot tidak membuat order, menangkap saldo, atau
melampirkan hasil provider kembali untuk transaksi itu, termasuk setelah restart.
User menerima notifikasi privat dengan retry; retry hanya mengirim pemberitahuan.
Tombol hanya tersedia pada owner untuk transaksi belum pasti tanpa ID order yang
tercatat. Permintaan yang masih berjalan harus ditunggu hingga selesai/timeout.
Pembatalan ini berlaku di bot: API provider belum mendokumentasikan cancel,
sehingga pesanan yang sudah diterima provider dapat tetap berjalan dan modalnya
menjadi tanggungan toko. Tidak perlu command refund tambahan atau variabel baru.

**Refund saldo Sosmed otomatis** saat API mengonfirmasi gagal (`Error/Failed`):
harga yang dibayar dikembalikan penuh. Untuk `Partial`, refund = harga dibayar ×
jumlah belum terpenuhi (`remains`) ÷ jumlah pesanan, dibulatkan ke bawah.
Jumlah partial yang hilang/invalid diperiksa dahulu. Refund menggunakan snapshot
harga order, ledger idempotent dan notifikasi privat dengan retry setelah restart.
Refund saldo toko tidak menunggu refund provider. Modal provider yang belum
dikembalikan tetap menjadi biaya toko; profit tidak menganggap kredit provider
sukses hanya dari status/charge. Bukti kredit provider owner dicatat terpisah tanpa
menambah saldo user dua kali. Pembatalan langsung di provider tetap memerlukan
dukungan API; Batalkan & Refund pada transaksi ditahan menutup transaksi lokal bot.

## Harga dan layanan Sosmed

Modal & Jual berisi 6 layanan per halaman, nama singkat, dan tarif **per 1.000**.
Owner melihat modal terendah dulu; user melihat harga jual terendah dulu.
Pilih Kategori dan Refresh Layanan memakai katalog asli provider. Menu user
menyediakan pintasan **TikTok** dan **Instagram**, lalu kategori yang benar-benar
tersedia; platform kosong tidak dibuatkan layanan fiktif.
Tarif `price`/`rate` dibaca dengan Decimal tanpa dikalikan 1.000 saat sinkronisasi;
kolom yang bertentangan dinonaktifkan. Modal pecahan rupiah tampil tepat pada owner.
Modal order = tarif API × jumlah ÷ 1.000. Harga jual tetap mengikuti pengaturan
markup, minimum transaksi dan pembulatan existing. Buka detail layanan →
**Rincian Harga** untuk memeriksa penyebab harga jual; pengaturan tidak direset.
Detail user menyebut harga pembelian minimum, dan konfirmasi tetap memakai
jumlah nyata. Price sorting/refresh tidak mengurangi wallet atau membuat order.

Tombol **Cari Layanan** tersedia di menu awal user/owner, kategori, TikTok/Instagram,
Modal & Jual, daftar layanan dan favorit. Ketik kata kunci seperti
`followers`/`likes`; kategori/platform/favorit yang sedang dibuka tetap dipakai.
Owner mendapat hasil Modal & Jual. Gunakan **Hapus Pencarian** untuk kembali
ke daftar tanpa kata kunci/filter. Kembali dan Menu Awal tersedia pada form cari.

Menu kategori memiliki **Cari Kategori** di atas daftar. Ketik nama/kata kunci,
misalnya `follower`, `likes`, atau `livestream`, lalu pilih kategori hasil pencarian.
TikTok/Instagram tetap membatasi hasil ke platform yang dipilih. Daftar berisi
8 kategori per halaman; Kembali dari layanan mempertahankan pencarian dan halaman.
**Hapus Pencarian Kategori** menampilkan kembali daftar kategori pada platform yang
sama. Pencarian ini tersedia juga pada kategori harga dan markup owner.

## Waktu dan invoice foto

Semua waktu tampilan memakai **WIB (Asia/Jakarta)**: transaksi, kedaluwarsa,
riwayat, rekening, OTP, Sosmed, pemeriksaan API, dan laporan harian.
Timestamp internal tetap dipakai sesuai sistem existing; tidak perlu variabel `TZ` baru.
Pembayaran berhasil mengirim invoice PNG privat untuk produk, isi saldo, OTP,
dan Sosmed. Nominal, metode, invoice dan waktu berasal dari pembayaran nyata;
isi saldo memisahkan saldo masuk dengan total transfer/kode unik.
Invoice tersimpan dalam antrean SQLite, dilindungi lease, dan dicoba ulang
setelah gagal/restart. Gagal mengirim foto tidak membatalkan pembayaran atau
menambah saldo kembali. Transaksi lama tidak dikirim massal setelah update.
Telegram belum menjamin pengiriman tepat sekali jika respons sukses hilang.
Tidak ada variabel atau dependency baru; `payment_receipts.py` wajib ikut diupload.

## Rekening transfer

Buka `/owner` → Pengaturan Pembayaran → Rekening Transfer. Tambah/edit bank, nomor,
pemilik, dan catatan; periksa data lama/baru lalu tekan Simpan. Rekening dapat
aktif/nonaktif, dijadikan utama, atau dihapus dari daftar dengan soft delete.
Menu rekening ringkas dalam empat baris. Tambah/Edit membuka form bertahap dengan
tombol Kembali/Batal; input mengganti pesan form yang sama sebelum konfirmasi.
User memilih rekening aktif ketika deposit/checkout. Invoice menyimpan rekening
dan nomor salin sendiri; perubahan rekening tidak mengubah snapshot invoice.
Tidak ada variabel baru atau wallet baru untuk multi-rekening.

## Konfirmasi pembayaran manual

Invoice **QRIS Manual dan Transfer Rekening** untuk pembelian maupun isi saldo
menunggu keputusan owner **tanpa batas waktu kedaluwarsa**. Tampilan user/owner
tidak memakai hitung mundur. Invoice pending lama dinormalisasi saat startup;
timer, cleanup expired, dan restart tidak menutup invoice manual yang menunggu.
Mode AUTO yang diaktifkan kemudian tidak mengubah metode invoice manual lama.

Owner tetap memakai tombol **Konfirmasi / Tolak / Tandai Pending** yang existing.
Invoice manual lama yang terlanjur expired bisa dikonfirmasi owner jika belum
dibatalkan, selesai, dibayar atau ditolak. Transaksi tidak dihidupkan ulang otomatis.
Stok/slot yang reservasinya pernah dilepas diperiksa ulang agar tidak mengambil
reservasi pembeli lain. Jika belum tersedia, pembayaran tercatat PAID dan menunggu
pemenuhan. Konfirmasi ganda aman; pembayaran/log atau kredit wallet disimpan atomik.
User/owner tetap dapat membatalkan invoice yang belum dibayar lewat alur existing.

Payment gateway otomatis tetap mengikuti masa berlaku existing/provider.
Quote harga, nomor/SMS OTP, draft pengaturan rekening dan konfirmasi Hapus Stok
tetap menggunakan masa berlaku yang sesuai; perubahan ini hanya untuk pembayaran
manual yang memerlukan owner. OTP/Sosmed tetap memakai saldo untuk pembelian baru.
Tidak ada Variables/dependency/command baru.

## Hapus stok owner

**/owner → Produk & Stok → Hapus Stok → Produk → Varian → Jumlah → Konfirmasi**.
Tombol juga tersedia di **Atur Stok → Varian**. Pilih 1/5/10, jumlah custom,
atau semua stok bebas (maksimal 10.000 per proses). Pilihan produk/varian memakai
8 item per halaman. Kembali/Batal tersedia; custom input mengganti pesan form.
Stok terbaru yang ditambahkan dipilih. Akun yang terjual/dialokasikan, akun
terhubung ke order, dan jumlah reservasi aktif dilindungi. Konfirmasi menyimpan
ID akun dan berlaku 10 menit; perubahan stok/reservasi memerlukan konfirmasi ulang.
Klik ganda/restart tidak menghapus akun lain. Akun ditandai `removed`, dikeluarkan
dari penjualan, dan dicatat pada Riwayat Stok/audit tanpa menghapus riwayat order.
Fitur ini khusus stok akun ready; alur slot Pre-Order/Famhead tetap memakai
pengaturan existing. Wallet, pembayaran dan alur OTP/Sosmed tidak diubah.

## Variabel

Isi `BOT_TOKEN` dan `ADMIN_ID` numerik melalui Railway Variables; daftar contoh ada di `.env.example`.
Sosmed memerlukan **BUZZERPANEL_API_KEY** dan **BUZZERPANEL_SECRET_KEY**.
Endpoint: `BUZZERPANEL_API_URL=https://buzzerpanel.id/api/json.php`.

Sesudah upload, ketik **`/sosmed`** sebagai owner. Gunakan tombol **Status API**
untuk memeriksa koneksi, lalu **Periksa & Buka Toko** untuk mengaktifkan toko.
Tombol berubah menjadi **Tutup Toko** saat aktif. Bot memeriksa profile/services
tanpa membuat order. Semua kontrol ini tersedia dalam menu yang sama.
Status API sekarang memeriksa koneksi saat dibuka, bukan hanya hasil terakhir.
Katalog besar kini dibaca bertahap melalui file sementara dengan batas khusus
64 MiB; decode berjalan pada worker. Respons order/profil tetap memakai batas lama.
Jika katalog gagal, saldo profil yang berhasil dibaca tetap tampil pada owner.
Validasi dilakukan per layanan: angka bulat seperti `100.0` dibaca dengan tepat,
duplikat identik digabung, dan entri invalid/ID konflik tidak dijual. Layanan valid
tetap diproses. Buka **Status API → Rincian Katalog** untuk ID, min/max, alasan
penolakan, serta jumlah layanan yang valid. Seluruh data invalid tetap menghentikan
pembelian; batas pecahan/format ambigu tidak dipaksakan menjadi jumlah.
Status menyebut **Profil/Katalog**, HTTP, dan penyebab yang aman: key ditolak,
izin IP, format respons, atau field saldo/harga yang perlu diperbaiki.
Saldo provider membaca `balance`/`saldo`; nilai hilang/bertentangan tidak dianggap nol.
Field pribadi pada Profile tidak ditampilkan dalam panel.
Katalog standar `id/price/note` tanpa `type` memakai form target + jumlah sesuai API;
catatan `note` tampil sebagai panduan username/URL. Layanan khusus yang belum jelas
bisa diatur owner: Modal & Jual → pilih layanan → **Tipe/Input** → konfirmasi.
Status `Success` berarti selesai; `Error` berarti gagal dengan refund saldo otomatis.
Daftar layanan user/owner berisi **6 pilihan per halaman**, dengan Sebelumnya,
Berikutnya, detail, dan **Refresh Layanan**. Refresh memperbarui harga, min/max,
catatan dan ketersediaan dari API; katalog juga diperbarui mengikuti TTL existing.
Harga/min/max tetap diperiksa ulang sebelum pembayaran. Wallet tidak berubah
karena membuka halaman atau memakai Refresh.
Verifikasi berhasil tersimpan di database dan bertahan setelah restart;
`SOSMED_API_CONTRACT_VERIFIED=true` tidak wajib untuk alur tombol ON ini.

Default `SOSMED_ENABLED=false` hanya untuk kondisi awal; pengaturan ON owner yang
tersimpan diprioritaskan. Kontrak refill/status_refill mengikuti pemeriksaan akun
pada tombol Status API; flag legacy `SOSMED_REFILL_API_VERIFIED=false` tidak
mengalahkan hasil verifikasi tersimpan atau keputusan Jeda Refill owner.
Jika Profile tidak menyebut mata uang, buka **Status API → Mata Uang & Satuan**:
konfirmasi **IDR** setelah saldo akun bertanda Rp, dan **/ 1.000** setelah kolom
harga layanan menyatakan tarif per 1.000. Kedua konfirmasi terpisah, tersimpan,
dan tidak memakai nilai saldo pada foto. Lalu tekan **Periksa & Buka Toko**.
Harga per 1.000 yang belum diketahui perlu dicek pada daftar layanan provider.
Alternatif Variables existing: `BUZZERPANEL_CURRENCY=IDR`, `SOSMED_RATE_UNIT=1000`;
keduanya opsional bila API/konfirmasi owner sudah menyebutnya. Nilai eksplisit API
tetap diperiksa, dan pergantian akun API memerlukan konfirmasi baru.
Cancel dan tipe yang belum didokumentasikan tidak diaktifkan.

OTP tetap memakai Variables existing; jika webhook digunakan, alamatnya
`https://DOMAIN_BOT_ANDA/webhooks/smscode/otp`.

## Isi paket

Sembilan file Python aktif: `main.py`, `bot.py`, `otp_smscode.py`,
`sosmed_buzzerpanel.py`, `sosmed_ui.py`, `project_backup.py`, `bank_accounts.py`,
`payment_receipts.py`, `klikqris_gateway.py`.
File pendukung: `requirements.txt`, `README.md`, `.env.example`, `.gitignore`,
`.python-version`, `railway.json`.

Tes, fixture bot lama, log, database, arsip backup, dan dokumentasi panjang
tersedia di paket lengkap/backup terpisah. Kode runtime sama dengan rilis
v17.17; hasil verifikasi dan backup tersedia dalam laporan rilis terpisah.

Backup penuh: `python project_backup.py --help`. Simpan arsip dan kunci di luar
project, terpisah dan privat; sertakan volume/DB yang benar-benar tersedia.
Restore ke lokasi baru dahulu; jangan menimpa database produksi dengan snapshot lama.
Jangan upload `.env` asli, database, session, backup privat, atau kunci ke GitHub.


Footer toko pada v17.17: **Maboyy Digital • Since 2020**.
Perubahan footer mempertahankan tombol dan alur pembayaran existing.

## Refill Sosmed

Owner membuka **/sosmed → Status API**: pemeriksaan profile/katalog berhasil
menyimpan kontrak `refill`/`status_refill` untuk akun yang sama. Buka **Status Refill**
untuk daftar 4 pengajuan per halaman, cek status, atau Jeda/Aktifkan Refill.
Tidak ada command/Variables baru dan pemeriksaan ini tidak membuat refill percobaan.
User membuka pesanan selesai → **Request Refill → Ajukan Refill**. Jika katalog
tidak memberi flag refill, kelayakan ditentukan saat pengajuan; flag tidak mendukung
tetap ditolak. Refill mengikuti ketentuan layanan dan tidak memotong saldo bot.
Tombol **Cek Status Refill**/Refresh Pesanan serta worker memperbarui status
melalui ID refill yang benar, termasuk saat toko/pengajuan baru dijeda.
Timeout/hasil tidak pasti tidak diajukan ulang otomatis. Tanpa ID refill, owner
perlu memeriksa pengajuan di akun provider sebelum mengambil tindakan lanjutan.
Kegagalan refill tidak mengubah order asli atau menambah refund saldo.


## QRIS Otomatis KlikQRIS

Variables baru: `KLIKQRIS_API_KEY`, `KLIKQRIS_MERCHANT_ID`; mode awal
`KLIKQRIS_MODE=gateway`, `KLIKQRIS_ENABLED=false`, `KLIKQRIS_SANDBOX=false`.
Buka **/owner → Pengaturan Pembayaran → QRIS Otomatis → Aktifkan KlikQRIS**.
Pemeriksaan koneksi membaca API, tanpa membuat transaksi. QRIS manual, transfer
rekening dan ShopeePay existing dipertahankan. User hanya melihat **⚡ QRIS Otomatis**.
Webhook: `https://DOMAIN_BOT_ANDA/webhooks/klikqris`; atur pada dashboard KlikQRIS.
Opsional `KLIKQRIS_WEBHOOK_URL`; bila kosong memakai PUBLIC_BASE_URL existing.
Polling tetap memantau pembayaran bila webhook terlambat. Provider `total_amount`
menjadi total final; kode unik manual tidak ditambahkan. Fee/penyesuaian ditampilkan.
Signature callback dicocokkan dengan signature invoice. Pembukuan selalu memerlukan
status, referensi dan nominal dari API resmi; polling memakai pemeriksaan API yang
sama. Screenshot tidak dapat menyetujui pembayaran otomatis.

MY PG tetap nonaktif sampai merchant terhubung. Pemilihan mode MY PG meminta ID
transaksi MY PG yang sudah ada untuk pemeriksaan API read-only; tidak memakai
session/cookie Shopee. API publik tidak menyediakan endpoint status koneksi merchant
khusus. Tanpa bukti tersebut, gunakan gateway biasa/manual.
Sandbox hanya untuk pengujian terisolasi; tidak dapat mengkredit wallet/produk nyata.
Jika create timeout, invoice tidak dibuat ulang otomatis. Gunakan Cek Status atau
Rekonsiliasi owner. Pembayaran setelah pembatalan masuk pemeriksaan owner; pilihan
Pindahkan ke Saldo memerlukan konfirmasi, bukti API dan ledger idempotent.
Pembayaran normal dan pemindahan tersebut memakai antrean invoice foto existing.
Tidak ada endpoint cancel/refund provider yang dikarang. Backup helper lama tetap
mencakup seluruh project; jangan upload database, .env, kunci atau backup ke GitHub.
