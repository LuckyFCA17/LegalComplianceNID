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
        "ruang terbatas", "ketinggian", "radiasi", "sistem manajemen k3", "p2k3", "tempat kerja",
        "panitia pembina keselamatan",
    ],
    "Lingkungan": [
        "lingkungan hidup", "amdal", "ukl-upl", "upaya pengelolaan lingkungan",
        "persetujuan lingkungan", "limbah", "b3", "bahan berbahaya dan beracun",
        "baku mutu", "air limbah", "emisi", "udara ambien", "pencemaran", "kerusakan lingkungan",
        "sampah", "kebisingan", "getaran", "kebauan", "air permukaan", "gas rumah kaca",
        "proper", "pengendalian pencemaran", "perlindungan dan pengelolaan lingkungan",
        "konservasi", "kehutanan", "sumber daya air", "ozon", "ukl", "upl",
        "upaya pemantauan lingkungan", "analisis mengenai dampak lingkungan",
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


# Long names per short jenis, so "peraturan pemerintah 50" or "permenaker 5" find the right rows.
JENIS_NAMES = {
    "UU": "undang-undang undang undang uu",
    "Perppu": "peraturan pemerintah pengganti undang-undang perppu",
    "PP": "peraturan pemerintah pp",
    "Perpres": "peraturan presiden perpres",
    "Keppres": "keputusan presiden keppres",
    "Inpres": "instruksi presiden inpres",
    "Permenaker": "peraturan menteri ketenagakerjaan tenaga kerja transmigrasi permenaker permenakertrans permen",
    "Kepmenaker": "keputusan menteri ketenagakerjaan tenaga kerja transmigrasi kepmenaker kepmenakertrans kepmen",
    "Permen LHK": "peraturan menteri lingkungan hidup dan kehutanan permen lhk permenlhk",
    "Permen LH": "peraturan menteri lingkungan hidup permen lh permenlh",
    "Kepmen LH(K)": "keputusan menteri lingkungan hidup kehutanan kepmen lh lhk kepmenlh",
    "Permenkes": "peraturan menteri kesehatan permenkes permen",
    "Permen ESDM": "peraturan menteri energi sumber daya mineral permen esdm",
    "Permen PUPR": "peraturan menteri pekerjaan umum perumahan rakyat permen pupr",
    "Permenperin": "peraturan menteri perindustrian permenperin permen",
    "Perda": "peraturan daerah perda",
}
# Words that only structure a citation ("PP Nomor 50 Tahun 2012 tentang ...") or join words in a title.
SEARCH_STOPWORDS = {
    "nomor", "no", "nmr", "tahun", "thn", "th", "tentang", "ttg", "tgl",
    "dan", "di", "ke", "dari", "atau", "yang", "dalam", "pada", "serta", "bagi", "untuk", "oleh", "atas", "the",
    # fragments of old ministry numbers typed apart: "PER 02 MEN 1980", "KEP 186 MEN 1999"
    "per", "kep", "men", "menlhk", "setjen", "kum",
}
_TOKEN_RE = re.compile(r"[\w.]+", re.UNICODE)
# Generic hints ("peraturan menteri ...") match every ministry regulation of that form.
_JENIS_FAMILY = {"Permen": "Permen", "Kepmen": "Kepmen"}


def _tokens(text):
    q = (text or "").lower().replace("/", " ").replace("-", " ")
    out = []
    for tok in _TOKEN_RE.findall(q):
        tok = tok.strip(".")
        if tok.startswith("no.") and tok[3:]:
            tok = tok[3:]  # "No.5" -> "5"
        if tok and tok not in SEARCH_STOPWORDS:
            out.append(tok)
    return out


# Composite regulation numbers: PER.02/MEN/1980, KEP.186/MEN/1999, P.68/MENLHK/SETJEN/KUM.1/8/2016.
_COMPOSITE_RE = re.compile(r"(?<![\w.])[a-z]{0,6}[.\-]?\d+(?:/[a-z0-9.\-]+)+")


def _norm_number(text):
    """'PER.02/MEN/1980' -> 'per2men1980' so spelling variants (PER-02, Per.2) compare equal."""
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", re.sub(r"[^0-9a-z]", "", (text or "").lower()))


def parse_search(query):
    """Split a search into the type it names, composite numbers, plain numbers and words.

    "Permenaker No. 2 Tahun 1980"
        -> jenis "Permenaker", numbers ["2", "1980"]
    "Peraturan Menteri Tenaga Kerja dan Transmigrasi Nomor PER.02/MEN/1980"
        -> jenis "Permenaker", composites ["per.02/men/1980"]
    "pemeriksaan kesehatan tenaga kerja"
        -> words ["pemeriksaan", "kesehatan", "tenaga", "kerja"]
    """
    text = " ".join((query or "").lower().split())
    jenis = None
    for pattern, short in JENIS_PATTERNS:
        m = re.search(pattern, text)
        if m:
            jenis = short
            text = (text[:m.start()] + " " + text[m.end():]).strip()  # the type's words need no title match
            break
    composites = _COMPOSITE_RE.findall(text)
    text = _COMPOSITE_RE.sub(" ", text)
    tokens = _tokens(text)
    numbers = [t for t in tokens if t.isdigit()]
    words = [t for t in tokens if not t.isdigit()]
    # "per.02" or "no5"-like codes typed without slashes behave as numbers too.
    codes = [w for w in words if re.search(r"\d", w)]
    return {
        "jenis": jenis,
        "composites": composites,
        "numbers": numbers,
        "codes": codes,
        "words": [w for w in words if w not in codes],
    }


def search_tokens(query):
    """Flat token list (kept for callers that only need the words of a query)."""
    return _tokens(query)


def _word_in(tok, text):
    if len(tok) <= 3:  # short tokens ("pp", "k3", "men") must be whole words
        return re.search(rf"(?<![\w.]){re.escape(tok)}(?![\w])", text) is not None
    return tok in text


def search_score(row, search):
    """Rank of a regulation for a parsed search (parse_search), or None when it does not match.

    Per-word scheme:
      * a type named in the search (UU, PP, Permenaker, ...) must match the regulation's type;
      * a composite number (PER.02/MEN/1980) must equal the regulation number (+4), or its first
        number must equal the regulation number and its year the regulation year (+2);
      * every plain number must match: the regulation number exactly (+3), the year (+2), a segment
        of a composite number (+1) or a number written in the title (+0.5);
      * codes such as "per.02" must be part of the regulation number (+2) or equal its number (+1);
      * other words are looked up in the title and number (+1 each, +1 more if all are found,
        +2 more if they appear as one phrase in the title, +2 more if they are the whole title);
        at least 60% of them must be found.
    """
    if isinstance(search, (list, tuple)):  # tolerate a flat token list
        search = parse_search(" ".join(search))
    jenis = row["jenis"] or ""
    if search.get("jenis"):
        family = _JENIS_FAMILY.get(search["jenis"])
        if not (jenis == search["jenis"] or (family and jenis.startswith(family))):
            return None
    nomor = str(row["nomor"] or "").lower()
    nomor_norm = _norm_number(nomor)
    nomor_plain = nomor.lstrip("0") or "0"
    tahun = str(row["tahun"] or "")
    judul = (row["judul"] or "").lower()
    nomor_parts = {p.lstrip("0") or "0" for p in re.split(r"[^0-9a-z]+", nomor) if p}
    score = 1.0 if search.get("jenis") else 0.0

    for comp in search.get("composites", []):
        if _norm_number(comp) == nomor_norm:
            score += 4
            continue
        # "2/1980" vs No. 2 Tahun 1980 or PER.02/MEN/1980: same first number and same year.
        digits = re.findall(r"\d+", comp)
        first = (digits[0].lstrip("0") or "0") if digits else None
        years = [d for d in digits[1:] if len(d) == 4]
        row_first = re.findall(r"\d+", nomor)
        row_first = (row_first[0].lstrip("0") or "0") if row_first else None
        if first and first == row_first and (not years or years[-1] == tahun):
            score += 2
        else:
            return None

    for tok in search.get("numbers", []):
        num = tok.lstrip("0") or "0"
        if num == nomor_plain:
            score += 3
        elif tok == tahun:
            score += 2
        elif num in nomor_parts:
            score += 1
        elif re.search(rf"(?<!\d){re.escape(tok)}(?!\d)", judul):
            score += 0.5
        else:
            return None

    for code in search.get("codes", []):
        code_norm = _norm_number(code)
        digits = re.findall(r"\d+", code)
        if code_norm and code_norm in nomor_norm:
            score += 2
        elif digits and (digits[0].lstrip("0") or "0") in nomor_parts:
            score += 1
        else:
            return None

    words = search.get("words", [])
    if words:
        text = " ".join([jenis.lower(), nomor, judul])
        found = sum(1 for w in words if _word_in(w, text))
        if found < max(1, -(-len(words) * 3 // 5)):  # at least 60% of the words, rounded up
            return None
        score += found + (1 if found == len(words) else 0)
        phrase = " ".join(words)
        if len(words) > 1 and phrase in judul:
            score += 2  # the words appear together as a phrase in the title
        if phrase == re.sub(r"\s+", " ", judul).strip():
            score += 2  # the title is exactly what was searched
    return score
