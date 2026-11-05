"""Offline (rule-based) analysis of a regulation's text: articles, requirements and sanctions.

Pipeline: PDF/text -> clean text -> Pasal / ayat units -> requirement candidates.
Candidates are suggestions for a person to review; nothing here is legal advice.
"""
import io
import re

MAX_PDF_BYTES = 40 * 1024 * 1024
SCANNED_CHARS_PER_PAGE = 200  # below this a PDF is most likely a scan without a text layer


class AnalysisError(ValueError):
    pass


# ---------------------------------------------------------------- text extraction & cleaning
_NOISE_LINE = re.compile(
    r"^(www\.[\w.-]+|jdih\.[\w.-]+|-\s*\d+\s*-|\d+\s*/\s*\d+|halaman\s+\d+(\s+dari\s+\d+)?|\d{1,3}|"
    r"\d{4},\s*no\.?\s*\d+.*|salinan|presiden republik indonesia|menteri [a-z ]+republik indonesia)$",
    re.IGNORECASE)
_HEADING = re.compile(r"^(pasal\s+\d+[a-z]?|bab\s+[ivxlcdm]+\b.*|bagian\s+\w+.*|paragraf\s+\d+.*|penjelasan\b.*)$",
                      re.IGNORECASE)
_BLOCK_START = re.compile(r"^(\(\d+[a-z]?\)|[a-z]\.\s|\d+\.\s)")


EMPTY_PAGE_CHARS = 80  # a page with less text than this is treated as an image (needs OCR)


def page_texts(data):
    """Raw text layer of every page of a PDF."""
    if len(data) > MAX_PDF_BYTES:
        raise AnalysisError("File PDF terlalu besar (maks. 40 MB)")
    if not data.startswith(b"%PDF"):
        raise AnalysisError("File ini bukan PDF")
    try:
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]
    except Exception as exc:  # broken or encrypted PDFs
        raise AnalysisError(f"PDF tidak dapat dibaca: {exc}") from exc


def inspect_pdf(data):
    """{text, pages, scanned, empty_pages}: empty_pages = indexes of pages without a usable text layer."""
    pages = page_texts(data)
    raw = "\n".join(pages)
    return {
        "text": clean_text(raw),
        "pages": len(pages),
        "scanned": len(raw.strip()) < SCANNED_CHARS_PER_PAGE * max(1, len(pages)),
        "empty_pages": [i for i, t in enumerate(pages) if len(t.strip()) < EMPTY_PAGE_CHARS],
    }


def extract_pdf(data):
    """Text of a PDF. Returns (text, pages, scanned) — scanned=True when there is (almost) no text layer."""
    info = inspect_pdf(data)
    return info["text"], info["pages"], info["scanned"]


def clean_text(raw):
    """Remove page furniture, re-join hyphenated words and wrapped lines, keep structural line breaks."""
    text = (raw or "").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)  # penyeleng-\ngaraan -> penyelenggaraan
    blocks = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if not line or _NOISE_LINE.match(line):
            continue
        if not blocks or _HEADING.match(line) or _BLOCK_START.match(line) or _HEADING.match(blocks[-1]):
            blocks.append(line)
        else:
            blocks[-1] += " " + line
    return "\n".join(blocks)


# ---------------------------------------------------------------- articles
_PASAL_LINE = re.compile(r"^pasal\s+(\d+[a-z]?)$", re.IGNORECASE)
_PENJELASAN = re.compile(r"^penjelasan\b", re.IGNORECASE)
# An ayat starts a line ("(2) Kewajiban ..."); "ayat (1)" inside a sentence is a reference, not a new ayat.
_AYAT = re.compile(r"(?:^|\n)\((\d+[a-z]?)\)\s+")


def split_articles(text):
    """[{pasal, number, text, units: [{ayat, text}]}] for the body; the elucidation (Penjelasan) is skipped."""
    articles, current = [], None
    for line in (text or "").split("\n"):
        m = _PASAL_LINE.match(line.strip())
        if _PENJELASAN.match(line.strip()) and articles:
            break  # the elucidation repeats "Pasal N" headings; it explains, it does not oblige
        if m:
            current = {"number": m.group(1).upper(), "lines": []}
            articles.append(current)
        elif current is not None:
            current["lines"].append(line)
    out = []
    for a in articles:
        body = "\n".join(a.pop("lines")).strip()
        units = []
        marks = list(_AYAT.finditer(body))
        if marks:
            for i, mk in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
                units.append({"ayat": mk.group(1), "text": " ".join(body[mk.end():end].split())})
        elif body:
            units.append({"ayat": None, "text": " ".join(body.split())})
        out.append({"pasal": f"Pasal {a['number']}", "number": a["number"], "text": " ".join(body.split()),
                    "units": units})
    return out


# ---------------------------------------------------------------- requirements
_MODAL = re.compile(r"\b(wajib|diwajibkan|berkewajiban|harus|dilarang|tidak boleh|tidak diperbolehkan|"
                    r"tidak diperkenankan)\b", re.IGNORECASE)
_PROHIBIT = re.compile(r"\b(dilarang|tidak boleh|tidak diperbolehkan|tidak diperkenankan)\b", re.IGNORECASE)
_REPORT = re.compile(r"\b(melapor|melaporkan|menyampaikan laporan|laporan|pelaporan)\b", re.IGNORECASE)
_PERMIT = re.compile(r"\b(memiliki|mendapatkan|memperoleh|mengajukan)\b[^.;]{0,80}?\b(izin|persetujuan|pengesahan|"
                     r"sertifikat|lisensi|surat keterangan|dokumen lingkungan|amdal|ukl-upl|sppl|rptka)\b",
                     re.IGNORECASE)
_SANCTION = re.compile(r"\b((dikenai|dikenakan|dijatuhi|diberikan)\s+sanksi|sanksi administratif|dipidana|"
                       r"pidana (penjara|denda|kurungan)|teguran tertulis|pencabutan izin)\b", re.IGNORECASE)
_TIMING = [
    re.compile(r"\bpaling (lambat|lama|sedikit|singkat)\s+[^.;,]{0,50}?\b(hari|minggu|bulan|tahun)(\s+(kerja|kalender))?\b",
               re.IGNORECASE),
    re.compile(r"\b(setiap|sekurang-kurangnya|minimal|sekali dalam|1 \(satu\) kali dalam)\s+[^.;,]{0,25}?\b"
               r"(hari|minggu|bulan|tahun|semester|triwulan)\b", re.IGNORECASE),
    re.compile(r"\b(secara berkala|berkala|sebelum [^.;,]{3,40}|sejak [^.;,]{3,40})\b", re.IGNORECASE),
]
_PASAL_REF = re.compile(r"\bPasal\s+(\d+[A-Z]?)", re.IGNORECASE)

# Who carries the duty, matched in the words just before the modal verb (last match wins).
_PARTIES = [
    ("pemerintah", r"menteri|pemerintah(?: pusat| daerah)?|gubernur|bupati|wali ?kota|pengawas ketenagakerjaan|"
                   r"pegawai pengawas|direktur jenderal|kepala dinas|instansi|badan penyelenggara|bpjs|lembaga"),
    ("perusahaan", r"setiap orang|setiap pengusaha|pengusaha|pengurus|perusahaan|pemberi kerja|penanggung ?jawab "
                   r"(?:usaha|kegiatan)|pelaku usaha|pemrakarsa|penghasil limbah|pengelola|pemilik|badan usaha|"
                   r"pengguna jasa|penyedia jasa|pihak yang bertanggung jawab"),
    ("pekerja", r"pekerja(?:/buruh)?|buruh|tenaga kerja|ahli k3|ahli keselamatan|operator|petugas|personil|personel|"
                r"teknisi|dokter perusahaan"),
]
_PARTY_RE = [(name, re.compile(rf"\b({pat})\b", re.IGNORECASE)) for name, pat in _PARTIES]
PARTY_LABEL = {"perusahaan": "Perusahaan / pengusaha", "pekerja": "Pekerja / personel K3",
               "pemerintah": "Pemerintah / instansi", "lainnya": "Tidak disebut"}
TYPE_LABEL = {"kewajiban": "Kewajiban", "larangan": "Larangan", "pelaporan": "Pelaporan",
              "perizinan": "Perizinan / dokumen"}


def _party(before):
    best, pos = "lainnya", -1
    for name, rx in _PARTY_RE:
        for m in rx.finditer(before):
            if m.start() > pos:
                best, pos = name, m.start()
    return best


def _timing(text):
    for rx in _TIMING:
        m = rx.search(text)
        if m:
            return " ".join(m.group(0).split())
    return None


def _shorten(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + " …"


def _describe(unit_text, modal, party):
    """'Setiap pengusaha wajib menerapkan SMK3 ...' -> 'Menerapkan SMK3 ...' (editable before it is added).

    Passive or subject-less sentences keep their subject: 'Audit SMK3 harus dilakukan berkala'
    -> 'Audit SMK3 dilakukan berkala'.
    """
    rest = unit_text[modal.end():].strip(" ,:")
    rest = re.sub(r"^untuk\s+", "", rest, flags=re.IGNORECASE)
    passive = re.match(r"di[a-z]{3,}\b", rest, re.IGNORECASE)
    if _PROHIBIT.match(modal.group(0)):
        rest = "Dilarang " + rest
    elif passive or party == "lainnya":
        before = unit_text[:modal.start()]
        clause = re.split(r"[.;:]\s+", before)[-1].strip(" ,")
        clause = clause[:1].upper() + clause[1:] if clause else ""
        rest = (clause + " " + rest).strip() if clause else rest
    rest = _shorten(rest, 220)
    return rest[:1].upper() + rest[1:] if rest else _shorten(unit_text, 220)


def analyze(text):
    """Requirement candidates and sanctions found in a regulation's text."""
    articles = split_articles(text)
    candidates, sanctions = [], []
    for art in articles:
        definitions = art["number"] == "1" and re.search(r"yang dimaksud dengan", art["text"], re.IGNORECASE)
        for unit in art["units"]:
            body = unit["text"]
            ref = art["pasal"] + (f" ayat ({unit['ayat']})" if unit["ayat"] else "")
            if _SANCTION.search(body):
                sanctions.append({"pasal": ref, "text": _shorten(body, 400),
                                  "refers_to": sorted({f"Pasal {n.upper()}" for n in _PASAL_REF.findall(body)})})
                continue
            if definitions:
                continue
            modal = _MODAL.search(body)
            if not modal:
                continue
            if _PROHIBIT.match(modal.group(0)):
                kind = "larangan"
            elif _PERMIT.search(body[modal.start():]):
                kind = "perizinan"
            elif _REPORT.search(body[modal.start():]):
                kind = "pelaporan"
            else:
                kind = "kewajiban"
            party = _party(body[max(0, modal.start() - 120):modal.start()])
            strong = modal.group(0).lower() in ("wajib", "diwajibkan", "berkewajiban", "dilarang")
            candidates.append({
                "pasal": ref, "article": art["pasal"], "type": kind, "type_label": TYPE_LABEL[kind],
                "party": party, "party_label": PARTY_LABEL[party],
                "confidence": "tinggi" if strong and party in ("perusahaan", "pekerja") else
                              ("sedang" if strong or party in ("perusahaan", "pekerja") else "rendah"),
                "timing": _timing(body), "description": _describe(body, modal, party), "quote": _shorten(body, 600),
                "context": _shorten(art["text"], 1200) if len(art["units"]) > 1 else None,
                # Pre-select what a company usually has to act on; government duties start unticked.
                "suggested": party in ("perusahaan", "pekerja", "lainnya") and party != "pemerintah",
            })
    # Link sanctions back to the requirement they enforce ("... sebagaimana dimaksud dalam Pasal 5 ...").
    by_article = {}
    for s in sanctions:
        for ref in s["refers_to"]:
            by_article.setdefault(ref, []).append(s["pasal"])
    for c in candidates:
        c["sanction"] = sorted(set(by_article.get(c["article"], [])))
    counts = {}
    for c in candidates:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    return {"articles": len(articles), "candidates": candidates, "sanctions": sanctions, "counts": counts}


# ---------------------------------------------------------------- full-text search
def snippet(text, words, width=90):
    """A short excerpt where the search words occur: the whole phrase if present, else the longest word."""
    low = text.lower()
    tries = [" ".join(words)] + sorted(words, key=len, reverse=True)
    for w in tries:
        i = low.find(w.lower())
        if i >= 0:
            start, end = max(0, i - width), min(len(text), i + len(w) + width)
            return ("…" if start else "") + " ".join(text[start:end].split()) + ("…" if end < len(text) else "")
    return None
