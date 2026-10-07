# Maboyy Digital Bot

**Versi aktif:** v16.35

## v16.35 — Statistik & Kuota `/tools`

Fitur baru owner-only:

- tombol `📊 Statistik & Kuota`;
- statistik sukses, gagal, pending;
- total request akun;
- tingkat keberhasilan dihitung dari request yang sudah selesai;
- kuota lokal per jam;
- estimasi sisa request;
- estimasi sisa kapasitas akun;
- reset otomatis setiap awal jam WIB;
- countdown ke reset berikutnya;
- request baru diblokir secara lokal jika sisa kuota kurang dari biaya per akun;
- statistik dan riwayat disimpan dari `tool_provision_logs`.

Variable tambahan:
```text
TOOLS_PROVIDER_HOURLY_LIMIT=15
TOOLS_PROVIDER_REQUESTS_PER_ACCOUNT=3
```

Nilai di atas cocok dengan panel provider yang menunjukkan 15 request API/jam dan estimasi 3 request untuk satu proses akun penuh.

Catatan: counter ini adalah pengaman lokal bot berdasarkan request yang dilakukan melalui bot. Provider tetap menjadi sumber kebenaran akhir jika memiliki counter sendiri.

Schema tetap 174.
