"""Helpers for Indonesian regulation citations: parsing, normalising, categorising."""
import re

CATEGORIES = ["K3", "Lingkungan", "Ketenagakerjaan", "Lainnya"]

# Keyword lists are matched against the lower-cased title ("tentang ...").
# Order matters: the first category with the highest score wins ties.
CATEGORY_KEYWORDS = {
    "K3": [
        "keselamatan dan kesehatan kerja", "keselamatan kerja", "kesehatan kerja", "k3",
        "smk3", "alat pelindung diri", "apd", "pesawat angkat", "pesawat uap", "bejana tekanan",
        "lift", "elevator", "eskalator", "penanggulangan kebakaran", "alat pemadam api",
        "kebakaran", "instalasi listrik", "penyalur petir", "lingkungan kerja", "ergonomi",
        "bahan kimia berbahaya", "pertolongan pertama pada kecelakaan", "p3k",
        "penyakit akibat kerja", "kecelakaan kerja", "ahli k3", "dokter perusahaan",
        "pengawasan ketenagakerjaan", "konstruksi bangunan", "perancah", "scaffolding",
        "ruang terbatas", "ketinggian", "radiasi",
    ],
    "Lingkungan": [
        "lingkungan hidup", "amdal", "ukl-upl", "upaya pengelolaan lingkungan",
        "persetujuan lingkungan", "limbah", "b3", "bahan berbahaya dan beracun",
        "baku mutu", "air limbah", "emisi", "udara ambien", "pencemaran", "kerusakan lingkungan",
        "sampah", "kebisingan", "getaran", "kebauan", "air permukaan", "gas rumah kaca",
        "proper", "pengendalian pencemaran", "perlindungan dan pengelolaan lingkungan",
        "konservasi", "kehutanan", "sumber daya air", "ozon",
    ],
    "Ketenagakerjaan": [
        "ketenagakerjaan", "tenaga kerja", "pekerja", "buruh", "upah", "pengupahan",
        "waktu kerja", "waktu istirahat", "lembur", "perjanjian kerja", "pkwt",
        "alih daya", "outsourcing", "pemutusan hubungan kerja", "phk", "pesangon",
        "jaminan sosial", "bpjs", "jaminan kecelakaan kerja", "jaminan kematian",
        "jaminan hari tua", "jaminan pensiun", "jaminan kehilangan pekerjaan",
        "serikat pekerja", "hubungan industrial", "peraturan perusahaan",
        "perjanjian kerja bersama", "tenaga kerja asing", "pelatihan kerja",
        "pemagangan", "tunjangan hari raya", "thr", "cipta kerja", "penyandang disabilitas",
    ],
}

# Canonical short names for regulation types, longest pattern first.
JENIS_PATTERNS = [
    (r"undang[- ]undang dasar", "UUD"),
    (r"peraturan pemerintah pengganti undang[- ]undang|perppu", "Perppu"),
    (r"undang[- ]undang|\buu\b", "UU"),
    (r"peraturan pemerintah|\bpp\b", "PP"),
    (r"peraturan presiden|\bperpres\b", "Perpres"),
    (r"keputusan presiden|\bkeppres\b", "Keppres"),
    (r"instruksi presiden|\binpres\b", "Inpres"),
    (r"peraturan menteri ketenagakerjaan|peraturan menteri tenaga kerja( dan transmigrasi)?|"
     r"\bpermenaker(trans)?\b|\bpermennaker\b", "Permenaker"),
    (r"keputusan menteri ketenagakerjaan|keputusan menteri tenaga kerja( dan transmigrasi)?|"
     r"\bkepmenaker(trans)?\b|\bkepmennaker\b", "Kepmenaker"),
    (r"peraturan menteri lingkungan hidup dan kehutanan|\bpermen ?lhk\b", "Permen LHK"),
    (r"peraturan menteri lingkungan hidup|\bpermen ?lh\b", "Permen LH"),
    (r"keputusan menteri lingkungan hidup( dan kehutanan)?|\bkepmen ?lhk?\b", "Kepmen LH(K)"),
    (r"peraturan menteri kesehatan|\bpermenkes\b", "Permenkes"),
    (r"peraturan menteri energi dan sumber daya mineral|\bpermen ?esdm\b", "Permen ESDM"),
    (r"peraturan menteri pekerjaan umum( dan perumahan rakyat)?|\bpermen ?pupr\b", "Permen PUPR"),
    (r"peraturan menteri perindustrian|\bpermenperin\b", "Permenperin"),
    (r"surat edaran", "SE"),
    (r"peraturan menteri", "Permen"),
    (r"keputusan menteri", "Kepmen"),
    (r"peraturan daerah|\bperda\b", "Perda"),
    (r"peraturan gubernur|\bpergub\b", "Pergub"),
    (r"peraturan bupati|\bperbup\b", "Perbup"),
    (r"peraturan wali ?kota|\bperwal\b", "Perwal"),
    (r"peraturan badan|peraturan lembaga|peraturan kepala", "Peraturan Lembaga"),
]

CITATION_RE = re.compile(
    r"^(?P<jenis>.+?)\s+(?:nomor|no\.?)\s*(?P<nomor>[\w./\-]+?)\s+tahun\s+(?P<tahun>\d{4})"
    r"(?:\s+tentang\s+(?P<judul>.+))?$",
    re.IGNORECASE | re.DOTALL,
)


def normalize_jenis(text):
    t = " ".join((text or "").lower().split())
    for pattern, short in JENIS_PATTERNS:
        if re.search(pattern, t):
            return short
    return " ".join((text or "").split()).strip() or "Lainnya"


def parse_citation(text):
    """Parse e.g. 'Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018 tentang K3 Lingkungan Kerja'.

    Returns dict(jenis, nomor, tahun, judul) or None when the text is not a citation.
    """
    clean = " ".join((text or "").split())
    m = CITATION_RE.match(clean)
    if not m:
        return None
    judul = (m.group("judul") or "").strip()
    return {
        "jenis": normalize_jenis(m.group("jenis")),
        "nomor": m.group("nomor").strip().upper().rstrip("."),
        "tahun": int(m.group("tahun")),
        "judul": judul[:1].upper() + judul[1:] if judul else "",
    }


def reg_key(jenis, nomor, tahun):
    nomor = re.sub(r"\s+", "", str(nomor)).upper()
    return f"{normalize_jenis(jenis).lower()}|{nomor}|{tahun or ''}"


def classify(judul, jenis=""):
    """Return the most likely compliance category for a regulation title."""
    text = f" {(judul or '').lower()} "
    scores = {}
    for cat, words in CATEGORY_KEYWORDS.items():
        score = 0
        for w in words:
            if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", text):
                score += 2 if " " in w else 1  # multi-word phrases are stronger evidence
        scores[cat] = score
    best = max(scores, key=lambda c: scores[c])
    if scores[best] > 0:
        return best
    if normalize_jenis(jenis) in ("Permenaker", "Kepmenaker"):
        return "Ketenagakerjaan"
    if normalize_jenis(jenis) in ("Permen LHK", "Permen LH", "Kepmen LH(K)"):
        return "Lingkungan"
    return "Lainnya"


def normalize_status(text):
    t = (text or "").lower()
    if "dicabut" in t or "tidak berlaku" in t:
        return "Dicabut"
    if "diubah" in t or "perubahan" in t:
        return "Diubah"
    return "Berlaku"


def citation(row):
    return f"{row['jenis']} No. {row['nomor']} Tahun {row['tahun']}"
