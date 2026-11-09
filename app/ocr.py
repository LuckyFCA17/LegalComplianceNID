"""Offline OCR for scanned regulation PDFs: PDFium renders the pages, Tesseract reads them.

Tesseract is looked up in this order: LCN_TESSERACT, a "tesseract" folder next to the program
(the portable Windows package ships one), the PATH, then the usual Windows install folders.
Indonesian ("ind") is used when its language data is present, English otherwise.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

DPI = 300
PAGE_TIMEOUT = 180  # seconds for one page
LOW_CONFIDENCE = 70  # mean word confidence (0-100) below which a page is flagged for checking


class OcrError(RuntimeError):
    pass


def _program_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_tesseract():
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    candidates = [os.environ.get("LCN_TESSERACT"), os.path.join(_program_dir(), "tesseract", exe),
                  shutil.which("tesseract")]
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.append(os.path.join(root, "Tesseract-OCR", exe))
                candidates.append(os.path.join(root, "Programs", "Tesseract-OCR", exe))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _env(cmd):
    env = dict(os.environ)
    bundled = os.environ.get("LCN_TESSDATA") or os.path.join(os.path.dirname(cmd), "tessdata")
    if os.path.isdir(bundled):
        env["TESSDATA_PREFIX"] = bundled
    env.setdefault("OMP_THREAD_LIMIT", "1")  # several pages in parallel would compete for the same cores
    return env


def _run(args, timeout):
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console flashes on Windows
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags, env=_env(args[0]))


_STATUS = {}


def status(refresh=False):
    """{available, path, languages, lang, message} — cached; cheap to call from requests."""
    if _STATUS and not refresh:
        return dict(_STATUS)
    cmd = find_tesseract()
    info = {"available": False, "path": cmd, "languages": [], "lang": None, "lang_best": None, "message": ""}
    if not cmd:
        info["message"] = ("Tesseract OCR tidak ditemukan. Versi portable Windows sudah menyertakannya; untuk versi lain "
                           "pasang paket tesseract-ocr dan tesseract-ocr-ind (Termux: pkg install tesseract).")
    else:
        try:
            out = _run([cmd, "--list-langs"], 30)
            text = (out.stdout or b"").decode("utf-8", "replace") + (out.stderr or b"").decode("utf-8", "replace")
            langs = [ln.strip() for ln in text.splitlines()[1:] if re.fullmatch(r"[a-z_]{3,}", ln.strip())]
            info["languages"] = langs
            if "ind" in langs:
                info.update(available=True, lang="ind+eng" if "eng" in langs else "ind")
                # tessdata_best Indonesian, installed as "indbest", is used by the thorough mode.
                if "indbest" in langs:
                    info["lang_best"] = "indbest+eng" if "eng" in langs else "indbest"
            elif "eng" in langs:
                info.update(available=True, lang="eng",
                            message="Data bahasa Indonesia (ind) tidak ada; OCR memakai bahasa Inggris, hasil kurang akurat.")
            else:
                info["message"] = "Tesseract ditemukan, tetapi tanpa data bahasa (tessdata)."
        except (OSError, subprocess.SubprocessError) as exc:
            info["message"] = f"Tesseract tidak dapat dijalankan: {exc}"
    _STATUS.clear()
    _STATUS.update(info)
    return dict(info)


def page_count(pdf_bytes):
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(pdf_bytes))


LOW_WORD_CONFIDENCE = 70  # words read below this may be corrected afterwards; others are left alone


def _tsv_to_text(tsv):
    """Rebuild lines from Tesseract's TSV output; returns (text, mean word confidence or None)."""
    text, conf, _low = _tsv_parse(tsv)
    return text, conf


def _tsv_parse(tsv):
    """(text, mean word confidence, set of words read with low confidence)."""
    lines, confs, low = {}, [], set()
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1
        if not word or conf < 0:
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(word)
        confs.append(conf)
        if conf < LOW_WORD_CONFIDENCE:
            low.update(re.findall(r"[A-Za-z0-9éı]+", word))
    text = "\n".join(" ".join(words) for _key, words in sorted(lines.items()))
    return text, (sum(confs) / len(confs) if confs else None), low


def _ocr_file(cmd, lang, image_path):
    try:
        out = _run([cmd, image_path, "stdout", "-l", lang, "tsv"], PAGE_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"OCR satu halaman melebihi {PAGE_TIMEOUT} detik") from exc
    if out.returncode != 0:
        raise OcrError((out.stderr or b"").decode("utf-8", "replace").strip()[:300] or "Tesseract gagal")
    return _tsv_parse(out.stdout.decode("utf-8", "replace"))


def ocr_image(cmd, lang, image_path):
    """(text, mean confidence) of one image file."""
    text, conf, _low = _ocr_file(cmd, lang, image_path)
    return text, conf


QUALITIES = ("standar", "teliti")
RETRY_BELOW = 85  # standard mode: a page under this confidence is also read with thickened strokes


def _ocr_pil(st, image, lang, tmp, name):
    path = os.path.join(tmp, f"{name}.png")
    image.save(path)
    try:
        return _ocr_file(st["path"], lang, path)
    finally:
        os.remove(path)


def _score(text, conf, max_words):
    """Mean confidence, penalised when a variant read fewer words than the best one (dropped lines)."""
    words = len(text.split())
    return (conf or 0) - 30 * (1 - words / max_words if max_words else 1)


def ocr_page_image(st, page_image, quality, tmp):
    """Read one rendered page with several clean-ups and keep the best.

    Returns (text, conf, variant, low-confidence words)."""
    from PIL import ImageFilter

    from .ocr_prep import prepare

    base, _info = prepare(page_image, binarise=False)  # flat paper, stretched contrast, despeckled, deskewed
    variants = [("pra-proses", lambda: base)]
    thick = ("pra-proses + tebal", lambda: base.filter(ImageFilter.MinFilter(3)))  # faded typewriter ink
    langs = [st["lang"]]
    if quality == "teliti":
        variants = [("asli", lambda: page_image)] + variants + [thick]
        if st.get("lang_best"):
            langs.append(st["lang_best"])
    results = []
    for lang in langs:
        for name, make in variants:
            text, conf, low = _ocr_pil(st, make(), lang, tmp, f"v{len(results)}")
            results.append((text, conf, f"{name} · {'best' if 'best' in lang else 'standar'}", low))
        if quality == "standar" and (results[0][1] or 0) < RETRY_BELOW:
            text, conf, low = _ocr_pil(st, thick[1](), lang, tmp, "thick")
            results.append((text, conf, f"{thick[0]} · standar", low))
    max_words = max(len(r[0].split()) for r in results) or 1
    return max(results, key=lambda r: _score(r[0], r[1], max_words))


def ocr_pdf(pdf_bytes, pages, progress=None, cancelled=None, quality="standar"):
    """OCR the given page indexes. Returns {index: (text, confidence, variant, low-confidence words)};
    stops early when cancelled()."""
    import pypdfium2 as pdfium

    st = status()
    if not st["available"]:
        raise OcrError(st["message"])
    doc = pdfium.PdfDocument(pdf_bytes)
    results = {}
    with tempfile.TemporaryDirectory(prefix="lcn-ocr-") as tmp:
        for n, index in enumerate(pages, 1):
            if cancelled and cancelled():
                break
            page = doc[index]
            image = page.render(scale=DPI / 72, grayscale=True).to_pil()
            page.close()
            results[index] = ocr_page_image(st, image, quality, tmp)
            if progress:
                progress(n, len(pages))
    doc.close()
    return results


# ---------------------------------------------------------------- typical OCR misreads in regulations
def fix_ocr_text(text):
    """Repair misreads that break the article structure: 'PasaI 1O' -> 'Pasal 10', '(l)' -> '(1)'."""
    from .ocr_correct import fix_structure
    return fix_structure(text)
