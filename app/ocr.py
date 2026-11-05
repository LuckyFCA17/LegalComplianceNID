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
    bundled = os.path.join(os.path.dirname(cmd), "tessdata")
    if os.path.isdir(bundled):
        env["TESSDATA_PREFIX"] = bundled
    env.setdefault("OMP_THREAD_LIMIT", "1")  # several pages in parallel would compete for the same cores
    return env


def _run(args, timeout):
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console flashes on Windows
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)


_STATUS = {}


def status(refresh=False):
    """{available, path, languages, lang, message} — cached; cheap to call from requests."""
    if _STATUS and not refresh:
        return dict(_STATUS)
    cmd = find_tesseract()
    info = {"available": False, "path": cmd, "languages": [], "lang": None, "message": ""}
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


def _render(doc, index, path):
    page = doc[index]
    image = page.render(scale=DPI / 72, grayscale=True).to_pil()
    image.save(path)
    page.close()


def _tsv_to_text(tsv):
    """Rebuild lines from Tesseract's TSV output; returns (text, mean word confidence or None)."""
    lines, confs = {}, []
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
    text = "\n".join(" ".join(words) for _key, words in sorted(lines.items()))
    return text, (sum(confs) / len(confs) if confs else None)


def ocr_image(cmd, lang, image_path):
    try:
        out = _run([cmd, image_path, "stdout", "-l", lang, "tsv"], PAGE_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"OCR satu halaman melebihi {PAGE_TIMEOUT} detik") from exc
    if out.returncode != 0:
        raise OcrError((out.stderr or b"").decode("utf-8", "replace").strip()[:300] or "Tesseract gagal")
    return _tsv_to_text(out.stdout.decode("utf-8", "replace"))


def ocr_pdf(pdf_bytes, pages, progress=None, cancelled=None):
    """OCR the given page indexes. Returns {index: (text, confidence)}; stops early when cancelled()."""
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
            path = os.path.join(tmp, f"p{index}.png")
            _render(doc, index, path)
            results[index] = ocr_image(st["path"], st["lang"], path)
            os.remove(path)
            if progress:
                progress(n, len(pages))
    doc.close()
    return results


# ---------------------------------------------------------------- typical OCR misreads in regulations
_DIGITISH = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "i": "1", "|": "1",
                           "!": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})


def fix_ocr_text(text):
    """Repair misreads that break the article structure: 'PasaI 1O' -> 'Pasal 10', '(l)' -> '(1)'."""
    out = []
    for line in (text or "").split("\n"):
        s = line.strip()
        m = re.match(r"^(?:p\s*a\s*s\s*a\s*[l1I|]|pasa[l1I|])\s+([0-9OoIlDQ|!SsBZz]{1,4})([a-zA-Z]?)\s*$", s, re.IGNORECASE)
        if m:
            s = f"Pasal {m.group(1).translate(_DIGITISH)}{m.group(2).upper()}"
        s = re.sub(r"^\(([0-9OoIlDQ|!SsBZz]{1,2})\)", lambda mm: f"({mm.group(1).translate(_DIGITISH)})", s)
        s = re.sub(r"\bPasa[I1|]\b", "Pasal", s)
        s = re.sub(r"\bayat\s+\(([Il|!])\)", "ayat (1)", s)
        out.append(s)
    return "\n".join(out)
