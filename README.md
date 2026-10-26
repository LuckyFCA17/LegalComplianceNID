# Legal Compliance NID

Aplikasi register kepatuhan hukum (legal compliance) yang terhubung dengan database
peraturan perundang-undangan Indonesia (JDIH BPK RI, JDIH Kemnaker, dan feed JDIHN).

## Tujuan
- **Menghimpun** daftar peraturan perundang-undangan beserta status berlakunya (Berlaku / Diubah / Dicabut).
- **Mengidentifikasi** peraturan yang relevan bagi organisasi (Relevan / Tidak relevan / Belum dinilai).
- **Melacak aktivitas pemenuhan** tiap peraturan relevan dan status pemenuhannya.

## Fitur
| Fitur | Keterangan |
|---|---|
| Koneksi & update database peraturan | Konektor JDIH BPK RI (`peraturan.bpk.go.id`), JDIH Kemnaker (`jdih.kemnaker.go.id`), feed JSON format JDIHN (URL dapat dikonfigurasi), impor CSV/JSON, serta katalog awal offline ±40 regulasi kunci. Sinkronisasi memperbarui status berlaku tanpa menimpa keputusan relevansi, kategori manual, maupun data pemenuhan. |
| Penentuan relevansi | Tombol Relevan / Tidak / ? per regulasi, aksi massal, catatan alasan. Saat ditandai relevan, usulan kewajiban (pasal + aktivitas) otomatis dibuat bila tersedia. |
| Dashboard progres | Tingkat pemenuhan (%), progres per kategori, progres penilaian relevansi, kewajiban lewat tenggat, regulasi relevan yang diubah/dicabut (perlu ditinjau), regulasi relevan tanpa kewajiban, status sinkronisasi sumber. |
| Pilih kategori | K3, Lingkungan, Ketenagakerjaan (dan Lainnya). Klasifikasi otomatis berbasis kata kunci, dapat dikoreksi manual. Pilihan kategori memfilter seluruh tampilan dan sinkronisasi. |
| Register pemenuhan | Kewajiban per regulasi: pasal, PIC, tenggat, status (Belum / Dalam proses / Terpenuhi / Tidak berlaku), bukti, catatan. Ekspor CSV. |

Tingkat pemenuhan = kewajiban *Terpenuhi* ÷ (total kewajiban − *Tidak berlaku*).

## Menjalankan
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python run.py                # buka http://localhost:5000
```
Saat pertama dibuka, Anda diminta membuat akun admin.
Database SQLite dibuat di `instance/compliance.db` (ubah dengan env `LCN_DATABASE`) dan diisi katalog awal saat pertama kali dijalankan.

Sinkronisasi dari CLI (cocok untuk cron/penjadwalan rutin):
```bash
flask --app run sync                                 # semua sumber aktif
flask --app run sync --source bpk --category K3      # sumber & kategori tertentu
```

Tes:
```bash
pytest -q
```

## Login & peran pengguna
Semua halaman memerlukan login. Ada tiga peran:

| Peran | Hak akses |
|---|---|
| **Admin** | Semua akses, termasuk kelola pengguna (tab *Pengguna*) dan konfigurasi sumber data |
| **Editor** | Menilai relevansi, mengisi kewajiban & status pemenuhan, impor, menjalankan sinkronisasi |
| **Viewer** | Hanya melihat dashboard/daftar dan mengekspor CSV |

Admin pertama dibuat dengan salah satu cara berikut:
- variabel lingkungan `ADMIN_EMAIL` + `ADMIN_PASSWORD` (dibuat otomatis saat start bila belum ada pengguna) — **wajib untuk server online**;
- halaman setup di browser saat pertama kali dibuka (hanya bila `LCN_REQUIRE_ENV_ADMIN` tidak aktif, cocok untuk pemakaian lokal);
- CLI: `flask --app run create-user --email admin@perusahaan.co.id --role admin`.

Login gagal 10 kali dalam 15 menit dari IP yang sama akan diblokir sementara.

## Deploy online (Render)
File `render.yaml` sudah disiapkan (Render Blueprint, region Singapura, disk persisten 1 GB untuk database).

1. Buat akun di https://render.com dan hubungkan dengan akun GitHub.
2. Pilih **New → Blueprint**, pilih repositori ini dan branch yang berisi aplikasi.
3. Render akan meminta nilai **`ADMIN_EMAIL`** dan **`ADMIN_PASSWORD`** — isi dengan akun admin Anda (password kuat, min. 8 karakter). `SECRET_KEY` dibuat otomatis.
4. Klik **Apply**. Setelah build selesai, aplikasi tersedia di `https://legal-compliance-nid.onrender.com` (atau nama yang Anda pilih) dan bisa dibuka dari laptop, tablet, maupun ponsel.
5. Login sebagai admin, lalu tambahkan akun tim di tab **Pengguna**.

Catatan biaya: disk persisten hanya tersedia pada instance berbayar (paket *Starter*). Paket gratis
Render tidak menyimpan file sehingga database akan hilang setiap restart/deploy — jangan gunakan untuk data nyata.

Variabel lingkungan yang dipakai:

| Variabel | Fungsi |
|---|---|
| `SECRET_KEY` | Kunci tanda tangan sesi (bila kosong dibuat acak & disimpan di samping database) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Akun admin pertama |
| `LCN_DATABASE` | Lokasi file SQLite (di Render: `/var/data/compliance.db`) |
| `LCN_SECURE_COOKIES=1` | Cookie sesi hanya lewat HTTPS |
| `LCN_BEHIND_PROXY=1` | Percayai header `X-Forwarded-*` dari load balancer |
| `LCN_REQUIRE_ENV_ADMIN=1` | Matikan halaman setup admin di browser |
| `WEB_CONCURRENCY` | Jumlah worker gunicorn (default 2) |

**Alternatif lain:** `Dockerfile` tersedia untuk Railway, Fly.io, VPS, atau server kantor:
```bash
docker build -t legal-compliance .
docker run -d -p 8000:8000 -v lcn-data:/data \
  -e ADMIN_EMAIL=admin@perusahaan.co.id -e ADMIN_PASSWORD='ganti-password-kuat' \
  -e LCN_REQUIRE_ENV_ADMIN=1 legal-compliance
```
Pasang di belakang HTTPS (reverse proxy) dan set `LCN_SECURE_COOKIES=1` + `LCN_BEHIND_PROXY=1`.

**Backup:** salin file database (`/var/data/compliance.db`) secara berkala, misalnya lewat *Shell* di dashboard Render:
`sqlite3 /var/data/compliance.db ".backup /var/data/backup.db"`.

## Konfigurasi sumber data
Di tab **Sumber Data**, tiap sumber memiliki URL dasar dan konfigurasi JSON:

| Kunci | Berlaku untuk | Arti |
|---|---|---|
| `keywords` | bpk, kemnaker | Daftar kata kunci pencarian (default: per kategori terpilih) |
| `max_pages` | bpk, kemnaker | Jumlah halaman hasil per kata kunci (default 2) |
| `search_url` | bpk, kemnaker | Template URL pencarian, placeholder `{base}`, `{q}`, `{page}` |
| `link_pattern` | bpk, kemnaker | Regex href tautan detail peraturan pada halaman hasil |
| `feed_url` | jdihn | URL feed JSON integrasi JDIHN dari situs JDIH anggota |

Konektor HTML bersifat heuristik (mencari tautan detail, sitasi "… Nomor X Tahun Y", teks "tentang …"
dan label Berlaku/Dicabut). Jika situs JDIH mengubah tampilan, sesuaikan `search_url` / `link_pattern`
tanpa mengubah kode. Bila akses langsung tidak tersedia, gunakan impor CSV
(`jenis,nomor,tahun,judul,status,url,category`) atau JSON format JDIHN.

> **Catatan:** status berlaku pada katalog awal disusun sebagai titik awal dan harus diverifikasi
> melalui sinkronisasi atau halaman JDIH resmi sebelum dijadikan dasar keputusan kepatuhan.

## Struktur
```
app/
  __init__.py        app factory + perintah CLI `sync` dan `create-user`
  auth.py            login, sesi, peran (admin/editor/viewer), kelola pengguna
  db.py              skema SQLite
  legal.py           parsing sitasi, normalisasi jenis, klasifikasi kategori
  sync.py            sinkronisasi & upsert (menjaga keputusan pengguna)
  routes.py          REST API + dashboard + ekspor
  connectors/        seed (katalog awal), html_search (BPK, Kemnaker), jdihn (feed JSON)
  static/            SPA (HTML/CSS/JS tanpa dependensi eksternal)
tests/               pytest
```
