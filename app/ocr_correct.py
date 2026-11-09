"""Rule-based correction of OCR text from regulations (no AI): structure first, then words.

1. Structure: article headings ("Pasal:.3", "PasaI l0", a heading whose number was lost) and
   ayat markers ("(l)", "{1)") are repaired, missing article numbers are inferred from the sequence.
2. Words: a token that is not in the lexicon is replaced only when exactly one variant made from
   typical typewriter/OCR confusions (rn<->m, cl<->d, l<->1, e<->c, ...) IS in the lexicon.
   The lexicon = a built-in list of legal/administrative Indonesian + words of regulation texts
   in the database that came from a clean text layer or were corrected by hand.
"""
import re
from collections import Counter

BASE_WORDS = """
ada adalah agar akan akibat aman amdal anak anggaran angka antara apabila asal asing atas atau audit ayat
badan bagi bagian bahan bahaya bahwa baik baku bangunan bank bantuan barang baru batas bawah beban bebas
bekerja beracun berat berbahaya berdasarkan berhak berikut berkala berkewajiban berlaku bersama bersangkutan
bertanggung besar biaya bidang bulan buruh cara catatan cukup daerah dalam dan dapat dari dasar data denda
dengan di diatur diberikan dicabut dijatuhi dikenai dikenakan dilakukan dilaksanakan dilarang dimaksud
dinas dipidana direktur diri diubah diwajibkan dokter dokumen dua ekonomi emisi gedung gubernur guna hak
hal hari harus hasil hidup hubungan hukum hukuman ialah ijin ini instalasi instansi isi itu izin jabatan
jaminan jangka jasa jawab jenis jika juga jumlah kabupaten kali karena kebakaran keadaan kebijakan kecelakaan
kecuali kegiatan kehutanan keputusan kepala kepada kerja kerusakan kesehatan keselamatan ketentuan
ketenagakerjaan kewajiban keterangan khusus kondisi kota kurang kurungan laporan lain lainnya lambat lama
lampiran langsung lebih lembaga lingkungan lokasi luar maka manajemen manusia masa masing masyarakat melakukan
melaksanakan melanggar melaporkan memberikan memenuhi memiliki memperoleh mempekerjakan menerapkan menetapkan
mengatur mengenai menggunakan menimbang menjadi menteri mengingat menurut menyampaikan menyediakan mesin
milik minimal mulai mutu nasional negara nomor norma objek oleh operator orang paling panitia pasal pekerja
pekerjaan pelaksanaan pelanggaran pelaporan pelatihan pemberi pembina pemeriksaan pemerintah penanggulangan
pencemaran pendidikan penerapan penetapan pengawas pengawasan pengelolaan pengendalian pengesahan pengujian
pengupahan pengurus pengusaha penjelasan penyakit penyelenggaraan peraturan perizinan perlindungan perlu
persetujuan persyaratan pertama perubahan perusahaan pesawat pidana proses program provinsi pusat ratus
rencana republik ribu risiko ruang rupiah sampai sanksi saat salah satu sebagai sebagaimana sebelum secara
sedang sehingga sejak sekali sekurang selama selanjutnya selain semua sertifikat sesuai setelah setiap
setinggi sistem standar status surat syarat tahun tanda tanggal tanggung tata telah tempat tenaga tentang
teknis terhadap tersebut tertulis tiap tidak tiga tinggi tingkat transmigrasi tujuan uji umum undang upah
upaya usaha untuk wajib waktu walikota wilayah yang yaitu
sampah tanpa ergonomi pemutusan industrial hubungan perselisihan pemberitahuan penghargaan kompensasi pesangon
dilaporkan dilakukan diterima ditetapkan diundangkan disampaikan diperlukan digunakan diberlakukan dikecualikan
pengurus pengusaha penanggung pemrakarsa pemohon pemegang penerima pelaku lingkungan limbah air udara tanah
""".split()

# Typical confusions of typewriter faces / photocopies (both directions are listed explicitly).
CONFUSIONS = [("rn", "m"), ("m", "rn"), ("cl", "d"), ("d", "cl"), ("li", "h"), ("h", "li"), ("ii", "u"), ("u", "ii"),
              ("vv", "w"), ("1", "l"), ("l", "1"), ("I", "l"), ("l", "I"), ("1", "i"), ("i", "l"), ("l", "i"),
              ("0", "o"), ("o", "0"), ("5", "s"), ("e", "c"), ("c", "e"), ("n", "u"), ("u", "n"), ("t", "f"),
              ("f", "t"), ("a", "o"), ("o", "a"), ("j", "i"), ("i", "j"), ("8", "a"), ("é", "e"), ("ı", "i")]
_WORD = re.compile(r"[A-Za-z0-9éı]+")
_DIGIT_LIKE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})
PROTECTED = {"b3", "k3", "p3k", "p2k3", "smk3", "ukl", "upl", "sppl", "rkl", "rpl", "apd", "apar", "phk", "pkwt", "pkwtt"}


def build_lexicon(texts=()):
    """Set of known lowercase words: built-ins plus words seen at least twice in trusted texts."""
    counts = Counter()
    for t in texts:
        counts.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", t or ""))
    return Lexicon(set(BASE_WORDS) | {w for w, n in counts.items() if n >= 2})


def _variants(token, depth=2):
    seen, frontier = {token}, {token}
    for _ in range(depth):
        nxt = set()
        for t in frontier:
            for a, b in CONFUSIONS:
                start = t.find(a)
                while start != -1:
                    v = t[:start] + b + t[start + len(a):]
                    if v not in seen:
                        seen.add(v)
                        nxt.add(v)
                    start = t.find(a, start + 1)
        frontier = nxt
    seen.discard(token)
    return seen


def _match_case(src, word):
    if src.isupper():
        return word.upper()
    if src[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


class Lexicon(set):
    """A word set with a deletion index for fast 'nearest known word' lookups (SymSpell idea)."""

    def __init__(self, words=()):
        super().__init__(words)
        self._index = None

    def _deletes(self, word, depth=2):
        out, frontier = {word}, {word}
        for _ in range(depth):
            frontier = {w[:i] + w[i + 1:] for w in frontier for i in range(len(w))} - out
            out |= frontier
        return out

    def nearest(self, token):
        """The single closest known word within a length-dependent distance, else None."""
        if self._index is None:
            self._index = {}
            for w in self:
                if 4 <= len(w) <= 24:
                    for d in self._deletes(w):
                        self._index.setdefault(d, set()).add(w)
        limit = 1 if len(token) <= 7 else 2
        cands = set()
        for d in self._deletes(token, limit):
            cands |= self._index.get(d, set())
        scored = sorted((_distance(token, c), c) for c in cands if abs(len(c) - len(token)) <= limit)
        if not scored or scored[0][0] > limit:
            return None
        if len(scored) > 1 and scored[1][0] == scored[0][0]:
            return None  # ambiguous: leave it for a person
        return scored[0][1]


def _distance(a, b):
    """Levenshtein distance (small strings)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def correct_word(token, lexicon):
    low = token.lower()
    if token.isdigit() or low in lexicon or low in PROTECTED:
        return token
    digits = sum(c.isdigit() for c in token)
    if len(token) >= 3 and digits and digits >= len(token) - 1 and not token.isalpha():
        fixed = token.translate(_DIGIT_LIKE)  # 2O12 -> 2012, l00 -> 100
        return fixed if fixed.isdigit() else token
    if len(token) < 4:
        return token
    hits = {v.lower() for v in _variants(token) if v.lower() in lexicon and v.isalpha()}
    hits = {h for h in hits if not _affix_only(low, h)}
    if len(hits) == 1:
        return _match_case(token, hits.pop())
    if len(token) >= 5 and token.isalpha() and isinstance(lexicon, Lexicon):
        near = lexicon.nearest(low)
        if near and not _affix_only(low, near):
            return _match_case(token, near)
    return token


_PREFIXES = sorted(("me", "mem", "men", "meng", "meny", "pe", "pem", "pen", "peng", "peny", "per", "di", "ke",
                    "ber", "ter", "se"), key=len, reverse=True)


def _core(word):
    for pre in _PREFIXES:
        if word.startswith(pre) and len(word) - len(pre) >= 3:
            word = word[len(pre):]
            break
    return re.sub(r"(kan|an|nya|i)$", "", word)


def _affix_only(a, b):
    """True when two words differ by an affix ('pembinaan'/'pembina', 'pembakaran'/'kebakaran'), which is not
    an OCR misread. Same-length words differing by a letter ('peneriksaan') are treated as misreads."""
    if len(a) == len(b):
        return False
    return a in b or b in a or _core(a) == _core(b)


def correct_words(text, lexicon, only=None):
    """Correct words; with `only` (a set of words the OCR engine was unsure about) nothing else is touched."""
    changed = []

    def repl(m):
        if only is not None and m.group(0) not in only:
            return m.group(0)
        new = correct_word(m.group(0), lexicon)
        if new != m.group(0):
            changed.append((m.group(0), new))
        return new
    return _WORD.sub(repl, text), changed


_DIG = "0-9OoIlDQ|!SsBZz"
_DIGITISH = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "i": "1", "|": "1",
                           "!": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})
# "Pasal 3", "Pasal:.3", "PasaI l0", and headings followed by short noise from stains: "Pasal 3 : AN"
_HEADING = re.compile(rf"^[\W_]*(?:p\s*a\s*s\s*a\s*[l1I|!]|pasa[l1I|!]?)\b[\s:;.,'`\"~_\-]*([{_DIG}]{{1,4}})?"
                      rf"(?:\s*([A-Za-z])(?![A-Za-z]))?((?:[\W_]+[A-Za-z0-9]{{1,2}})*)[\W_]*$", re.IGNORECASE)
_AYAT = re.compile(rf"^[\W_]{{0,2}}[\(\{{\[]([{_DIG}]{{1,2}})[\)\}}\]]\s*")
_LEAD_JUNK = re.compile(r"^[~«»“”\"'`|_•·*]+\s*(?=[A-Za-z(])")


def fix_structure(text):
    """Repair article headings and ayat markers; infer heading numbers lost in OCR from the sequence."""
    lines = [ln.strip() for ln in (text or "").split("\n")]
    heads = []  # (line index, number or None, suffix letter)
    for i, s in enumerate(lines):
        s = _LEAD_JUNK.sub("", s)
        m = _HEADING.match(s)
        if m and len(s) <= 24:
            num = m.group(1).translate(_DIGITISH) if m.group(1) else None
            suffix = (m.group(2) or "").upper() if m.group(1) else ""
            heads.append([i, int(num) if num and num.isdigit() else None, suffix])
            s = "Pasal"
        else:
            s = _AYAT.sub(lambda mm: f"({mm.group(1).translate(_DIGITISH)}) ", s, count=1)
            s = re.sub(r"^BAB\s+([|l1!]+|[|l1!]*[IVXL]+[|l1!]*)$",
                       lambda mm: "BAB " + re.sub(r"[|l1!]", "I", mm.group(1)), s)  # BAB | -> BAB I
        lines[i] = s
    # Infer missing numbers: Pasal 4, Pasal ?, Pasal 6 -> 5 (also at the start: ? then 2 -> 1).
    for k, h in enumerate(heads):
        if h[1] is not None:
            continue
        prev = next((x[1] for x in reversed(heads[:k]) if x[1] is not None), 0)
        nxt = next((x[1] for x in heads[k + 1:] if x[1] is not None), None)
        if nxt is None or nxt > prev + 1:
            h[1] = prev + 1
    for i, num, suffix in heads:
        lines[i] = f"Pasal {num}{suffix}" if num is not None else "Pasal"
    text = "\n".join(lines)
    # References inside sentences: "dalam PasaI 1O ayat (l)" -> "dalam Pasal 10 ayat (1)"
    text = re.sub(rf"\bPasa[lI1|]\s+([{_DIG}]{{1,3}})\b(?=\s*(?:ayat|huruf|dan|atau|,|\.|\)|$))",
                  lambda m: "Pasal " + m.group(1).translate(_DIGITISH), text)
    text = re.sub(r"\bayat\s+[\(\{\[]([Il|!1])[\)\}\]]", "ayat (1)", text)
    return text


_JUNK_TOKEN = re.compile(r"(?<!\S)[|$`~^°*#«»]+(?!\S)")


def correct(text, lexicon=None, only=None):
    """Structure + word correction. Returns (text, list of (old, new) word changes).

    Pass `only` = the words OCR read with low confidence: confidently read words are never changed.
    """
    text = _JUNK_TOKEN.sub("", fix_structure(text))
    if lexicon is None:
        lexicon = build_lexicon()
    return correct_words(text, lexicon, only)


_VOWEL = re.compile(r"[aeiou]", re.IGNORECASE)
_PUNCT_OK = set(" \n\t.,;:()-/\"'%&?!+=[]")


def text_quality(text, lexicon=None):
    """0-100 estimate of how readable a text is (detects poor OCR text layers in PDFs).

    Combines: share of words found in the lexicon, share of plausible words (letters only, has a vowel,
    no long consonant runs) and the share of junk symbols.
    """
    text = text or ""
    if len(text.strip()) < 200:
        return 0
    if lexicon is None:
        lexicon = build_lexicon()
    tokens = [t.strip(".,;:()\"'[]-") for t in text.split()]
    words = [t for t in tokens if len(t) >= 3]
    if not words:
        return 0
    known = sum(1 for w in words if w.lower() in lexicon) / len(words)
    plausible = sum(1 for w in words if w.isalpha() and _VOWEL.search(w)
                    and not re.search(r"[^aeiou\W\d_]{5,}", w, re.IGNORECASE)
                    and not re.search(r"[a-z][A-Z]", w)) / len(words)
    junk = sum(1 for c in text if not c.isalnum() and c not in _PUNCT_OK) / len(text)
    score = (0.45 * min(1.0, known / 0.6) + 0.55 * plausible) * (1 - min(0.6, junk * 4))
    return round(100 * score)
