# Maboyy Digital Bot

**Versi aktif:** v16.38

## v16.38 — Fix `/tools` Konfigurasi Belum Lengkap

Bug diperbaiki:
- status READY sebelumnya masih bergantung pada `TOOLS_PROVIDER_PROVISION_URL`;
- padahal flow aktif sekarang hanya Magic Link + Verify.

Sekarang `/tools` dianggap READY jika:
- `TOOLS_PROVIDER_ENABLED=true`
- `TOOLS_PROVIDER_API_KEY` tersedia di Railway Secret
- `TOOLS_PROVIDER_MAGICLINK_URL` terisi
- `TOOLS_PROVIDER_VERIFY_URL` terisi

`TOOLS_PROVIDER_STATUS_URL` dan `TOOLS_PROVIDER_PROVISION_URL` tidak lagi diwajibkan.

Menu `Cek API` sekarang memeriksa konfigurasi aktif tersebut dan menampilkan
variable mana yang benar-benar belum tersedia jika ada.

Schema tetap 174.
