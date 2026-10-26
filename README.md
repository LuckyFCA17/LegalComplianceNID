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
  __init__.py        app factory + perintah CLI `sync`
  db.py              skema SQLite
  legal.py           parsing sitasi, normalisasi jenis, klasifikasi kategori
  sync.py            sinkronisasi & upsert (menjaga keputusan pengguna)
  routes.py          REST API + dashboard + ekspor
  connectors/        seed (katalog awal), html_search (BPK, Kemnaker), jdihn (feed JSON)
  static/            SPA (HTML/CSS/JS tanpa dependensi eksternal)
tests/               pytest
```
