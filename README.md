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

## Pencarian regulasi
Kotak pencarian di tab *Regulasi* memecah teks per kata:

| Bagian yang diketik | Aturan |
|---|---|
| Jenis (`PP`, `Permenaker`, `peraturan menteri tenaga kerja dan transmigrasi`, `UU` …) | hasil dibatasi ke jenis itu; singkatan dan nama panjang setara |
| Nomor gabungan (`PER.02/MEN/1980`, `KEP.186/MEN/1999`) | harus sama dengan nomor regulasi; atau angka pertama + tahunnya sama (`No. 2 Tahun 1980`) |
| Angka (`2`, `1980`) | harus sama persis dengan nomor atau tahun — `5` tidak menemukan No. 15/50 |
| Kata lain (`pemeriksaan kesehatan`) | dicari di judul & nomor; minimal 60% kata harus ditemukan |
| `nomor`, `no.`, `tahun`, `tentang`, `dan`, `di`, `dalam` … | diabaikan |

Hasil diurutkan dari yang paling cocok: nomor persis, lalu tahun, lalu jumlah kata dan frasa judul yang sama.
Contoh yang setara: `Permenaker No. 2 Tahun 1980`, `permenaker 2/1980`, `PER.02/MEN/1980`,
`Peraturan Menteri Tenaga Kerja dan Transmigrasi Nomor PER.02/MEN/1980`.

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
Di tab **Sumber Data**, tiap sumber memiliki URL dasar dan konfigurasi JSON.

| Sumber | Cara kerja | Halaman peraturan | PDF |
|---|---|---|---|
| JDIH BPK RI | Pencarian kata kunci per kategori (`/Search?keywords=…&p=N`) | `/Details/{id}/{slug}` | `/Download/{id}/{file}.pdf` |
| JDIH Kemnaker | Pencarian katalog (`/peraturan?hal=N&keyword=…&sort=terbaru`) | `/peraturan/detail/{id}/{slug}` | `/asset/data_puu/….pdf` |

Setiap sinkronisasi:
1. mengambil daftar peraturan dan menyimpan **tautan ke halaman peraturan itu sendiri** (bukan halaman pencarian);
2. membuka halaman tiap peraturan untuk mengambil **tautan PDF** dan status terkini (maks. `detail_limit` per sinkronisasi);
3. mencari halaman untuk peraturan yang belum tertaut (misalnya dari katalog awal) berdasarkan sitasinya —
   BPK lewat kata kunci, Kemnaker lewat filter nomor & tahun (maks. `lookup_limit`).

Jika teks hasil pencarian sulit dibaca, jenis/nomor/tahun diambil dari slug alamat halaman
(mis. `.../permenkes-no-11-tahun-2022`). Sertifikat SSL situs .go.id yang tidak lengkap ditangani otomatis
(`ssl_fallback`, dicatat di riwayat sinkronisasi).

Kata kunci pencarian bawaan (tampil juga di tab *Sumber Data*):

| Kategori | Kata kunci |
|---|---|
| K3 | keselamatan dan kesehatan kerja, keselamatan kerja, kesehatan kerja, SMK3, sistem manajemen K3, penyakit akibat kerja, kecelakaan kerja, P3K, P2K3, tempat kerja, pengusaha, kebakaran |
| Lingkungan | lingkungan hidup, limbah, baku mutu, pencemaran, sampah, UKL, UPL, AMDAL, emisi |
| Ketenagakerjaan | ketenagakerjaan, pengupahan, jaminan sosial |

Kategori setiap hasil tetap ditentukan dari judulnya, sehingga kata kunci umum seperti "pengusaha"
membantu menemukan peraturan tanpa otomatis memasukkannya ke K3.

Peraturan yang sudah dicek tidak dicek ulang selama 30 hari. Dari panel detail sebuah peraturan, editor juga bisa
menekan **Cari halaman & PDF di JDIH**, atau mengisi tautan halaman/PDF secara manual.

| Kunci | Berlaku untuk | Arti |
|---|---|---|
| `keywords` | bpk, kemnaker | Daftar kata kunci pencarian (default: per kategori terpilih) |
| `max_pages` | bpk, kemnaker | Jumlah halaman hasil per kata kunci (default 2 / 5) |
| `search_url` | bpk, kemnaker | Template URL, placeholder `{base}`, `{q}` (kata kunci), `{page}` |
| `lookup_url` | bpk, kemnaker | Template pencarian satu peraturan, placeholder `{q}`, `{jenis}`, `{nomor}`, `{tahun}` |
| `ssl_fallback` | semua | Coba ulang tanpa verifikasi SSL bila rantai sertifikat situs tidak lengkap (default `true`) |
| `link_pattern` | bpk, kemnaker | Regex href tautan halaman peraturan |
| `pdf_pattern` | bpk, kemnaker | Regex tautan PDF (default: `.pdf` atau `/download/`) |
| `detail_limit`, `lookup_limit` | bpk, kemnaker | Batas halaman detail / pencarian sitasi per sinkronisasi (default 30 / 20) |
| `delay` | semua | Jeda antar-permintaan dalam detik (default 0.5) |
| `user_agent` | semua | Ganti User-Agent bila situs menolak permintaan |
| `feed_url` | jdihn | URL feed JSON integrasi JDIHN dari situs JDIH anggota |

### Jika sinkronisasi gagal
Riwayat sinkronisasi menampilkan penyebabnya, misalnya `HTTP 403` (situs memblokir IP/bot), `HTTP 404`
(alamat berubah), atau "tidak ada peraturan yang dikenali" (tampilan situs berubah).

Tekan **Tes koneksi** pada kartu sumber (tab *Sumber Data*): aplikasi mengambil satu halaman hasil pencarian
dan satu halaman peraturan, lalu menampilkan apakah situs merespons, berapa tautan peraturan & PDF yang dikenali,
beserta contohnya. Dari terminal:
```bash
flask --app run inspect-source bpk --keyword "keselamatan kerja"
flask --app run inspect-source kemnaker
flask --app run inspect-source bpk --detail https://peraturan.bpk.go.id/Details/145520/permenaker-no-6-tahun-2017
```
Perintah ini menampilkan hasil parsing dan menyimpan HTML mentah di `instance/debug-<sumber>.html`. Sesuaikan
`search_url` / `link_pattern` / `pdf_pattern` tanpa mengubah kode. Bila akses langsung tetap tidak tersedia,
gunakan impor CSV (`jenis,nomor,tahun,judul,status,url,category`) atau JSON format JDIHN.

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
