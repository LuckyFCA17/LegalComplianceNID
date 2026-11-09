"""Offline OCR of scanned PDFs (needs Tesseract; skipped where it is not installed)."""
import io
import os
import time

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import create_app, ocr
from app.analysis import inspect_pdf
from app.auth import create_user
from app.db import get_db

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "contoh_peraturan.txt")
needs_tesseract = pytest.mark.skipif(not ocr.status(refresh=True)["available"], reason="Tesseract not installed")


def scanned_pdf(chunks, text_layer_first=None):
    """Image-only PDF pages (A4, 300 dpi) — like a scan; optionally prepend a normal text page."""
    font = ImageFont.load_default(size=40)
    images = []
    for lines in chunks:
        img = Image.new("L", (2480, 3508), 255)
        d = ImageDraw.Draw(img)
        y = 200
        for ln in lines:
            words, cur = ln.split(), ""
            for w in words:
                if d.textlength(cur + " " + w, font=font) > 2080:
                    d.text((200, y), cur.strip(), fill=0, font=font)
                    y, cur = y + 60, ""
                cur += " " + w
            d.text((200, y), cur.strip(), fill=0, font=font)
            y += 60
        images.append(img)
    buf = io.BytesIO()
    images[0].save(buf, "PDF", resolution=300, save_all=True, append_images=images[1:])
    data = buf.getvalue()
    if text_layer_first is None:
        return data
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for src in (text_layer_first, data):
        for page in PdfReader(io.BytesIO(src)).pages:
            w.add_page(page)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def fixture_chunks():
    lines = open(FIXTURE, encoding="utf-8").read().splitlines()
    return [lines[:22], lines[22:]]


def test_fix_ocr_misreads():
    fixed = ocr.fix_ocr_text("PasaI 1O\n(l) Setiap pengusaha wajib\nPasal l2A\nsebagaimana dimaksud dalam PasaI 5 ayat (l)")
    assert fixed.splitlines() == ["Pasal 10", "(1) Setiap pengusaha wajib", "Pasal 12A",
                                  "sebagaimana dimaksud dalam Pasal 5 ayat (1)"]
    assert ocr.fix_ocr_text("a. huruf biasa (a) tetap") == "a. huruf biasa (a) tetap"


def test_scanned_pages_are_detected():
    info = inspect_pdf(scanned_pdf(fixture_chunks()))
    assert info["scanned"] and info["empty_pages"] == [0, 1]


@needs_tesseract
def test_ocr_reads_a_scanned_page():
    res = ocr.ocr_pdf(scanned_pdf(fixture_chunks()), [1])
    text, conf, variant, unsure = res[1]
    assert variant.startswith("pra-proses")
    assert "dilarang mempekerjakan" in text and conf > 60


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "data" / "t.db"), "TESTING": True})


def login(app, role="editor"):
    with app.app_context():
        create_user(get_db(), f"{role}@x.co", role.title(), "rahasia123", role)
    c = app.test_client()
    c.post("/api/auth/login", json={"email": f"{role}@x.co", "password": "rahasia123"})
    return c


def upload(c, rid, data):
    return c.post(f"/api/regulations/{rid}/text/upload", data={"file": (io.BytesIO(data), "scan.pdf")},
                  content_type="multipart/form-data")


def wait_done(c, rid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        job = c.get(f"/api/regulations/{rid}/ocr").get_json()["job"]
        if job and not job["active"]:
            return job
        time.sleep(0.3)
    raise AssertionError("OCR did not finish")


@needs_tesseract
def test_upload_scan_run_ocr_and_analyse(app, tmp_path):
    c = login(app)
    rid = c.get("/api/regulations?category=K3&q=PP 50 2012").get_json()[0]["id"]
    a = upload(c, rid, scanned_pdf(fixture_chunks())).get_json()
    assert a["text"]["scanned"] and a["text"]["needs_ocr"] == 2 and a["text"]["has_pdf"]
    assert a["candidates"] == []
    assert os.path.isfile(tmp_path / "data" / "pdf" / f"{rid}.pdf")  # kept next to the database

    r = c.post(f"/api/regulations/{rid}/ocr")
    assert r.status_code == 202 and r.get_json()["job"]["status"] == "running"
    assert c.post(f"/api/regulations/{rid}/ocr").status_code == 409  # already running (any computer)
    job = wait_done(c, rid)
    assert job["status"] == "done" and job["done_pages"] == job["total_pages"] == 2, job

    a = c.get(f"/api/regulations/{rid}/analysis").get_json()
    assert a["text"]["origin"] == "ocr" and a["text"]["needs_ocr"] == 0 and a["text"]["ocr_pages"] == 2
    found = {x["pasal"] for x in a["candidates"]}
    assert {"Pasal 5 ayat (1)", "Pasal 9 ayat (1)", "Pasal 12", "Pasal 13"} <= found

    # Correct the OCR text by hand: analysis follows the edited text.
    text = c.get(f"/api/regulations/{rid}/text").get_json()["content"]
    edited = text.replace("dilarang mempekerjakan", "wajib menyediakan alat pelindung diri dan dilarang mempekerjakan")
    a = c.patch(f"/api/regulations/{rid}/text", json={"text": edited}).get_json()
    assert a["text"]["edited"]


@needs_tesseract
def test_mixed_pdf_only_ocrs_image_pages(app):
    from test_analysis import make_pdf
    lines = open(FIXTURE, encoding="utf-8").read().splitlines()
    mixed = scanned_pdf([lines[22:]], text_layer_first=make_pdf([lines[:22]]))
    c = login(app)
    rid = c.get("/api/regulations?category=K3&q=PP 50 2012").get_json()[0]["id"]
    a = upload(c, rid, mixed).get_json()
    assert not a["text"]["scanned"] and a["text"]["needs_ocr"] == 1
    c.post(f"/api/regulations/{rid}/ocr")
    job = wait_done(c, rid)
    assert job["total_pages"] == 1
    a = c.get(f"/api/regulations/{rid}/analysis").get_json()
    assert {"Pasal 5 ayat (1)", "Pasal 12"} <= {x["pasal"] for x in a["candidates"]}


def test_ocr_refused_without_pdf_or_tesseract(app, monkeypatch):
    c = login(app)
    rid = c.get("/api/regulations?category=K3&q=PP 50 2012").get_json()[0]["id"]
    c.post(f"/api/regulations/{rid}/text", json={"text": open(FIXTURE).read()})
    monkeypatch.setattr(ocr, "status", lambda refresh=False: {"available": True, "path": "x", "lang": "ind",
                                                               "message": "", "languages": ["ind"]})
    r = c.post(f"/api/regulations/{rid}/ocr")
    assert r.status_code == 400 and "PDF aslinya tidak tersimpan" in r.get_json()["error"]
    monkeypatch.setattr(ocr, "status", lambda refresh=False: {"available": False, "path": None, "lang": None,
                                                               "message": "Tesseract OCR tidak ditemukan.",
                                                               "languages": []})
    assert "tidak ditemukan" in c.post(f"/api/regulations/{rid}/ocr").get_json()["error"]
    assert c.get("/api/ocr/status").get_json()["available"] is False


def test_viewer_cannot_start_ocr(app):
    v = login(app, "viewer")
    rid = v.get("/api/regulations?category=K3&q=PP 50 2012").get_json()[0]["id"]
    assert v.post(f"/api/regulations/{rid}/ocr").status_code == 403


def test_bundled_tesseract_is_found_first(tmp_path, monkeypatch):
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    bundled = tmp_path / "tesseract" / exe
    bundled.parent.mkdir()
    bundled.write_text("")
    monkeypatch.delenv("LCN_TESSERACT", raising=False)
    monkeypatch.setattr(ocr, "_program_dir", lambda: str(tmp_path))
    assert ocr.find_tesseract() == str(bundled)
    monkeypatch.setenv("LCN_TESSERACT", str(bundled))
    assert ocr.find_tesseract() == str(bundled)
