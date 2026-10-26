"""Offline starter catalogue of key K3, environmental and labour regulations.

Used so the app is useful before (or without) network access to JDIH sites.
Status values reflect the editor's knowledge at time of writing and must be
re-verified through a live sync or the official JDIH page before relying on them.
Each entry may carry suggested obligations, which are created automatically
when the regulation is marked relevant.
"""
from .base import Connector, make_record

# (jenis, nomor, tahun, judul, status, [(pasal, kewajiban), ...])
CATALOG = [
    # ---- K3 -------------------------------------------------------------
    ("UU", "1", 1970, "Keselamatan Kerja", "Berlaku", [
        ("Pasal 3, 4", "Penuhi syarat-syarat keselamatan kerja di tempat kerja"),
        ("Pasal 8", "Pemeriksaan kesehatan badan tenaga kerja (awal & berkala)"),
        ("Pasal 9", "Pembinaan/penjelasan K3 kepada tenaga kerja baru"),
        ("Pasal 11", "Laporkan setiap kecelakaan kerja ke pejabat pengawas"),
        ("Pasal 14", "Pasang syarat K3, poster dan gambar K3 di tempat kerja; sediakan APD gratis"),
    ]),
    ("PP", "50", 2012, "Penerapan Sistem Manajemen Keselamatan dan Kesehatan Kerja", "Berlaku", [
        ("Pasal 5", "Terapkan SMK3 (wajib untuk ≥100 pekerja atau risiko bahaya tinggi)"),
        ("Pasal 7", "Tetapkan & sosialisasikan kebijakan K3 tertulis"),
        ("Pasal 16", "Lakukan audit SMK3 eksternal secara berkala"),
    ]),
    ("PP", "88", 2019, "Kesehatan Kerja", "Berlaku", [
        ("", "Selenggarakan upaya kesehatan kerja (pencegahan, peningkatan, penanganan PAK)"),
    ]),
    ("Permenaker", "5", 2018, "Keselamatan dan Kesehatan Kerja Lingkungan Kerja", "Berlaku", [
        ("Pasal 2", "Pengukuran & pengendalian faktor fisika, kimia, biologi, ergonomi, psikologi"),
        ("Pasal 3", "Penyediaan fasilitas kebersihan dan sanitasi"),
        ("Pasal 61", "Pengujian lingkungan kerja oleh personel/PJK3 yang berkompeten"),
    ]),
    ("Permenaker", "8", 2020, "Keselamatan dan Kesehatan Kerja Pesawat Angkat dan Pesawat Angkut", "Berlaku", [
        ("", "Pemeriksaan & pengujian berkala pesawat angkat/angkut, terbitkan SKP"),
        ("", "Operator memiliki lisensi K3 sesuai jenis pesawat"),
    ]),
    ("Permenaker", "6", 2017, "Keselamatan dan Kesehatan Kerja Elevator dan Eskalator", "Berlaku", [
        ("", "Riksa uji berkala elevator/eskalator dan pengesahan pemakaian"),
    ]),
    ("Permenaker", "37", 2016, "Keselamatan dan Kesehatan Kerja Bejana Tekanan dan Tangki Timbun", "Berlaku", [
        ("", "Riksa uji berkala bejana tekanan & tangki timbun"),
        ("", "Operator bejana tekanan memiliki lisensi K3"),
    ]),
    ("Permenaker", "12", 2015, "Keselamatan dan Kesehatan Kerja Listrik di Tempat Kerja", "Berlaku", [
        ("", "Pemeriksaan & pengujian instalasi listrik oleh Ahli K3 Listrik/PJK3"),
    ]),
    ("Permenaker", "9", 2016, "Keselamatan dan Kesehatan Kerja dalam Pekerjaan pada Ketinggian", "Berlaku", [
        ("", "Prosedur kerja di ketinggian dan tenaga kerja bersertifikat"),
        ("", "Sediakan alat pelindung jatuh perorangan yang laik"),
    ]),
    ("Permenaker", "8", 2010, "Alat Pelindung Diri", "Berlaku", [
        ("Pasal 2", "Sediakan APD sesuai SNI secara cuma-cuma"),
        ("Pasal 4", "Pasang rambu wajib APD di area kerja"),
    ]),
    ("Permenaker", "15", 2008, "Pertolongan Pertama pada Kecelakaan di Tempat Kerja", "Berlaku", [
        ("", "Sediakan petugas P3K terlatih dan fasilitas P3K (kotak P3K, ruang P3K)"),
    ]),
    ("Permenaker", "4", 1980, "Syarat-syarat Pemasangan dan Pemeliharaan Alat Pemadam Api Ringan", "Berlaku", [
        ("", "Pasang APAR sesuai jenis kebakaran dan jarak, beri tanda pemasangan"),
        ("", "Inspeksi APAR setiap 6 bulan dan pengujian berkala"),
    ]),
    ("Kepmenaker", "186", 1999, "Unit Penanggulangan Kebakaran di Tempat Kerja", "Berlaku", [
        ("", "Bentuk unit penanggulangan kebakaran dan petugas peran kebakaran"),
        ("", "Lakukan latihan penanggulangan kebakaran secara berkala"),
    ]),
    ("Perpres", "7", 2019, "Penyakit Akibat Kerja", "Berlaku", [
        ("", "Diagnosis PAK oleh dokter kompeten dan pelaporan kasus penyakit akibat kerja"),
    ]),
    ("Permenkes", "11", 2022, "Pelayanan Kesehatan Penyakit Akibat Kerja", "Berlaku", [
        ("", "Pelayanan kesehatan PAK melalui fasilitas pelayanan kesehatan / dokter perusahaan"),
    ]),
    ("Permenaker", "2", 1980, "Pemeriksaan Kesehatan Tenaga Kerja dalam Penyelenggaraan Keselamatan Kerja", "Berlaku", [
        ("", "Pemeriksaan kesehatan sebelum bekerja, berkala (min. 1x/tahun) dan khusus"),
    ]),
    ("Permenaker", "4", 1987, "Panitia Pembina Keselamatan dan Kesehatan Kerja serta Tata Cara Penunjukan Ahli Keselamatan Kerja", "Berlaku", [
        ("", "Bentuk P2K3 dan daftarkan pengesahannya"),
        ("", "Kirim laporan kegiatan P2K3 setiap 3 bulan"),
    ]),
    # ---- Lingkungan -----------------------------------------------------
    ("UU", "32", 2009, "Perlindungan dan Pengelolaan Lingkungan Hidup", "Diubah", [
        ("Pasal 22, 34", "Miliki dokumen lingkungan (AMDAL/UKL-UPL/SPPL) dan persetujuan lingkungan"),
        ("Pasal 59", "Kelola limbah B3 yang dihasilkan"),
    ]),
    ("PP", "22", 2021, "Penyelenggaraan Perlindungan dan Pengelolaan Lingkungan Hidup", "Berlaku", [
        ("", "Laporkan pelaksanaan RKL-RPL / UKL-UPL secara berkala (per semester)"),
        ("", "Penuhi persetujuan teknis pembuangan air limbah dan emisi"),
        ("", "Simpan limbah B3 di TPS berizin dan kirim ke pihak berizin dengan manifest"),
    ]),
    ("PP", "101", 2014, "Pengelolaan Limbah Bahan Berbahaya dan Beracun", "Dicabut", []),
    ("Permen LHK", "6", 2021, "Tata Cara dan Persyaratan Pengelolaan Limbah Bahan Berbahaya dan Beracun", "Berlaku", [
        ("", "Penuhi persyaratan teknis TPS limbah B3 (simbol, label, logbook)"),
        ("", "Neraca dan laporan pengelolaan limbah B3 berkala"),
    ]),
    ("Permen LHK", "4", 2021, "Daftar Usaha dan/atau Kegiatan yang Wajib Memiliki Analisis Mengenai Dampak Lingkungan Hidup, Upaya Pengelolaan Lingkungan Hidup dan Upaya Pemantauan Lingkungan Hidup atau Surat Pernyataan Kesanggupan Pengelolaan dan Pemantauan Lingkungan Hidup", "Berlaku", [
        ("", "Tentukan jenis dokumen lingkungan yang wajib untuk setiap kegiatan"),
    ]),
    ("Permen LH", "5", 2014, "Baku Mutu Air Limbah", "Berlaku", [
        ("", "Pemantauan kualitas air limbah sesuai baku mutu (min. 1x/bulan)"),
    ]),
    ("Permen LHK", "68", 2016, "Baku Mutu Air Limbah Domestik", "Berlaku", [
        ("", "Olah air limbah domestik hingga memenuhi baku mutu"),
    ]),
    ("Permen LHK", "11", 2021, "Baku Mutu Emisi Mesin dengan Pembakaran Dalam", "Berlaku", [
        ("", "Uji emisi genset/mesin pembakaran dalam secara berkala"),
    ]),
    ("Permen LHK", "1", 2021, "Program Penilaian Peringkat Kinerja Perusahaan dalam Pengelolaan Lingkungan Hidup", "Berlaku", []),
    ("Kepmen LH(K)", "48", 1996, "Baku Tingkat Kebisingan", "Berlaku", [
        ("", "Pemantauan tingkat kebisingan di batas kawasan"),
    ]),
    ("UU", "18", 2008, "Pengelolaan Sampah", "Berlaku", [
        ("", "Sediakan fasilitas pemilahan sampah di kawasan/fasilitas"),
    ]),
    ("PP", "27", 2020, "Pengelolaan Sampah Spesifik", "Berlaku", []),
    # ---- Ketenagakerjaan ------------------------------------------------
    ("UU", "13", 2003, "Ketenagakerjaan", "Diubah", [
        ("Pasal 108", "Miliki Peraturan Perusahaan yang disahkan (≥10 pekerja) atau PKB"),
        ("Pasal 86, 87", "Terapkan K3 dan SMK3 sebagai bagian manajemen perusahaan"),
    ]),
    ("UU", "6", 2023, "Penetapan Peraturan Pemerintah Pengganti Undang-Undang Nomor 2 Tahun 2022 tentang Cipta Kerja menjadi Undang-Undang", "Berlaku", [
        ("", "Sesuaikan PP/PKB dan perjanjian kerja dengan perubahan klaster ketenagakerjaan"),
    ]),
    ("UU", "11", 2020, "Cipta Kerja", "Dicabut", []),
    ("PP", "35", 2021, "Perjanjian Kerja Waktu Tertentu, Alih Daya, Waktu Kerja dan Waktu Istirahat, dan Pemutusan Hubungan Kerja", "Berlaku", [
        ("", "PKWT dibuat tertulis dan dicatatkan; bayar uang kompensasi saat PKWT berakhir"),
        ("", "Patuhi batas waktu kerja dan upah kerja lembur"),
        ("", "Hitung pesangon/UPMK/UPH sesuai ketentuan saat PHK"),
    ]),
    ("PP", "36", 2021, "Pengupahan", "Diubah", [
        ("", "Bayar upah tidak lebih rendah dari upah minimum"),
        ("", "Susun dan terapkan struktur dan skala upah"),
    ]),
    ("PP", "51", 2023, "Perubahan atas Peraturan Pemerintah Nomor 36 Tahun 2021 tentang Pengupahan", "Berlaku", []),
    ("PP", "34", 2021, "Penggunaan Tenaga Kerja Asing", "Berlaku", [
        ("", "Miliki RPTKA yang disahkan untuk setiap TKA; tunjuk tenaga kerja pendamping"),
    ]),
    ("UU", "24", 2011, "Badan Penyelenggara Jaminan Sosial", "Berlaku", [
        ("Pasal 15", "Daftarkan seluruh pekerja ke BPJS Ketenagakerjaan dan BPJS Kesehatan"),
    ]),
    ("PP", "44", 2015, "Penyelenggaraan Program Jaminan Kecelakaan Kerja dan Jaminan Kematian", "Diubah", [
        ("", "Laporkan kecelakaan kerja ke BPJS Ketenagakerjaan maks. 2x24 jam"),
    ]),
    ("PP", "37", 2021, "Penyelenggaraan Program Jaminan Kehilangan Pekerjaan", "Diubah", []),
    ("Permenaker", "6", 2016, "Tunjangan Hari Raya Keagamaan bagi Pekerja/Buruh di Perusahaan", "Berlaku", [
        ("", "Bayar THR paling lambat 7 hari sebelum hari raya keagamaan"),
    ]),
    ("UU", "21", 2000, "Serikat Pekerja/Serikat Buruh", "Berlaku", []),
    ("UU", "2", 2004, "Penyelesaian Perselisihan Hubungan Industrial", "Berlaku", []),
]


# Detail pages already known for some entries; the rest are linked by a BPK sync (lookup by citation).
KNOWN_PAGES = {
    ("UU", "1", 1970): "https://jdih.kemnaker.go.id/peraturan/detail/49/undang-undang-nomor-1-tahun-1970",
    ("Permenaker", "5", 2018):
        "https://jdih.kemnaker.go.id/peraturan/detail/1546/peraturan-menteri-ketenagakerjaan-nomor-5-tahun-2018",
    ("Permenaker", "6", 2017): "https://peraturan.bpk.go.id/Details/145520/permenaker-no-6-tahun-2017",
    ("Perpres", "7", 2019): "https://jdih.kemnaker.go.id/peraturan/detail/1588/peraturan-presiden-nomor-7-tahun-2019",
    ("Permenkes", "11", 2022): "https://peraturan.bpk.go.id/Details/218299/permenkes-no-11-tahun-2022",
    ("Permenaker", "12", 2015): "https://peraturan.bpk.go.id/Details/145984/permenaker-no-12-tahun-2015",
}


def catalog_records():
    for jenis, nomor, tahun, judul, status, obligations in CATALOG:
        yield make_record(
            jenis, nomor, tahun, judul, status=status, url=KNOWN_PAGES.get((jenis, nomor, tahun)),
            suggested=[{"pasal": p, "description": d} for p, d in obligations],
        )


class SeedConnector(Connector):
    kind = "seed"

    def fetch(self, categories=None):
        yield from catalog_records()
