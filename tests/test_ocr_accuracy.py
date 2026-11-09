"""OCR accuracy (pre-processing + correction) and re-OCR with review and text versions."""
import io
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import create_app, ocr, ocr_prep
from app.analysis import analyze, clean_text
from app.auth import create_user
from app.db import get_db
from app.ocr_correct import build_lexicon, correct, correct_words, fix_structure, text_quality
from test_analysis import make_pdf
from typewriter_scan import TEXT, cer, scanned_pdf

needs_tesseract = pytest.mark.skipif(not ocr.status(refresh=True)["available"], reason="Tesseract not installed")


# ---------------------------------------------------------------- pre-processing
def test_normalise_flattens_uneven_paper():
    a = np.tile(np.linspace(120, 240, 800, dtype=np.float32), (400, 1))  # dark-to-light page
    a[180:220, 100:700] -= 100  # a text line
    out = np.asarray(ocr_prep.normalise(Image.fromarray(a.astype(np.uint8))), dtype=np.float32)
    paper = np.concatenate([out[20:150, 50:750].ravel(), out[260:380, 50:750].ravel()])
    assert paper.std() < 12 and paper.mean() > 230  # flat white paper
    assert out[190:210, 150:650].mean() < 120  # text stays dark


def test_deskew_finds_rotation():
    img = Image.new("L", (1600, 1000), 255)
    d = ImageDraw.Draw(img)
    for y in range(100, 900, 60):
        d.rectangle((100, y, 1500, y + 18), fill=0)
    angle = ocr_prep.skew_angle(img.rotate(1.6, fillcolor=255))
    assert abs(angle + 1.6) <= 0.25


# ---------------------------------------------------------------- correction
def test_structure_repair():
    raw = "BAB |\nPasal\nYang dimaksud\nPasal '2 4 g :\n{l) Setiap pengusaha\nPasal:.3 AN\n\"Pasal 4\nPasaI\nPasal 6"
    fixed = fix_structure(raw).splitlines()
    assert fixed[0] == "BAB I"
    assert [ln for ln in fixed if ln.startswith("Pasal")] == ["Pasal 1", "Pasal 2", "Pasal 3", "Pasal 4", "Pasal 5",
                                                            "Pasal 6"]
    assert "(1) Setiap pengusaha" in fixed


def test_word_correction_and_safeguards():
    lex = build_lexicon()
    text, changes = correct("peneriksaan beraturen TRANSHIGRAST rnelakukan tahun 2O12 denda l00", lex)
    assert text.split() == ["pemeriksaan", "peraturan", "TRANSMIGRASI", "melakukan", "tahun", "2012", "denda", "100"]
    # abbreviations and affix variants are never "corrected"
    assert correct("limbah B3 dan K3 serta P2K3", lex)[1] == []
    assert correct_words("Pembinaan Laporkan pembakaran", lex)[1] == []
    # words the OCR engine read confidently are left alone, even if unknown
    assert correct_words("tanpa sampah beraturen", lex, only={"beraturen"})[0] == "tanpa sampah peraturan"


def test_text_quality_separates_good_and_poor_text():
    import random
    rnd = random.Random(1)
    garbled = "".join(rnd.choice("il1|rnmc0;:~^") if c.isalpha() and rnd.random() < 0.15 else c for c in TEXT)
    assert text_quality(TEXT) >= 90
    assert text_quality(garbled) < 70
    assert text_quality("pendek") == 0


@needs_tesseract
def test_heavily_degraded_typewriter_scan_is_now_readable():
    pdf, truth = scanned_pdf("berat", 11)
    res = ocr.ocr_pdf(pdf, [0], quality="standar")
    text, conf, variant, unsure = res[0]
    lex = build_lexicon()
    text = clean_text(correct(correct_words(text, lex, only=unsure)[0], lex, only=set())[0])
    assert cer(truth, text) < 0.15, cer(truth, text)
    assert analyze(text)["articles"] >= 4


# ---------------------------------------------------------------- re-OCR, review and versions
@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "data" / "t.db"), "TESTING": True})


@pytest.fixture
def client(app):
    with app.app_context():
        create_user(get_db(), "e@x.co", "Editor", "rahasia123", "editor")
    c = app.test_client()
    c.post("/api/auth/login", json={"email": "e@x.co", "password": "rahasia123"})
    return c


def reg_id(c):
    return c.get("/api/regulations?category=K3&q=Permenaker 2 1980").get_json()[0]["id"]


def upload(c, rid, data):
    return c.post(f"/api/regulations/{rid}/text/upload", data={"file": (io.BytesIO(data), "p.pdf")},
                  content_type="multipart/form-data").get_json()


def wait(c, rid, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        job = c.get(f"/api/regulations/{rid}/ocr").get_json()["job"]
        if job and not job["active"]:
            return job
        time.sleep(0.3)
    raise AssertionError("OCR did not finish")


def test_every_pdf_is_kept_and_poor_text_layer_is_flagged(client):
    rid = reg_id(client)
    junk = ["Pasa1 l ~ Pcng:ur.us wjb rnlkkn pmrksn kshtn ;; ^^ lll |||"] * 30
    a = upload(client, rid, make_pdf([junk]))
    assert a["text"]["has_pdf"] and a["text"]["needs_ocr"] == 0  # text-layer PDF kept as well
    assert a["text"]["poor_text"] and a["text"]["text_quality"] < 70
    good = upload(client, rid, make_pdf([TEXT.splitlines()[:30]]))
    assert not good["text"]["poor_text"]
    assert good["text"]["versions"] == 1  # the replaced upload was kept


def test_ocr_validation(client):
    rid = reg_id(client)
    upload(client, rid, make_pdf([TEXT.splitlines()[:30]]))
    assert client.post(f"/api/regulations/{rid}/ocr", json={"mode": "pages", "pages": "9"}).status_code == 400
    assert client.post(f"/api/regulations/{rid}/ocr", json={"mode": "pages", "pages": "1-x"}).status_code == 400
    assert client.post(f"/api/regulations/{rid}/ocr", json={"mode": "x"}).status_code == 400
    assert client.post(f"/api/regulations/{rid}/ocr", json={"quality": "super"}).status_code == 400


@needs_tesseract
def test_reocr_review_accept_restore_and_discard(client):
    rid = reg_id(client)
    pdf, _truth = scanned_pdf("sedang", 7)
    first = upload(client, rid, pdf)
    assert first["text"]["scanned"]
    client.post(f"/api/regulations/{rid}/ocr", json={"mode": "scan"})
    job = wait(client, rid)
    assert job["status"] == "done"  # nothing to lose: applied directly
    a = client.get(f"/api/regulations/{rid}/analysis").get_json()
    assert a["text"]["origin"] == "ocr" and a["text"]["ocr_mode"] == "scan/standar" and a["text"]["text_quality"] >= 85
    assert a["text"]["ocr_conf"] > 70

    # Correct by hand, then read again: the result now waits for a decision.
    original = client.get(f"/api/regulations/{rid}/text").get_json()["content"]
    client.patch(f"/api/regulations/{rid}/text", json={"text": original + "\nPasal 99\nCatatan tambahan wajib dibaca."})
    r = client.post(f"/api/regulations/{rid}/ocr", json={"mode": "all", "quality": "standar"})
    assert r.status_code == 202
    job = wait(client, rid)
    assert job["status"] == "review" and job["result"]["articles"] >= 5, job
    assert "Pasal 99" not in client.get(f"/api/regulations/{rid}/ocr/result").get_json()["content"]
    assert "Pasal 99" in client.get(f"/api/regulations/{rid}/text").get_json()["content"]  # unchanged until accepted

    client.post(f"/api/regulations/{rid}/ocr/discard")
    assert "Pasal 99" in client.get(f"/api/regulations/{rid}/text").get_json()["content"]

    client.post(f"/api/regulations/{rid}/ocr", json={"mode": "pages", "pages": "1"})
    assert wait(client, rid)["status"] == "review"
    a = client.post(f"/api/regulations/{rid}/ocr/accept").get_json()
    assert "Pasal 99" not in client.get(f"/api/regulations/{rid}/text").get_json()["content"]
    versions = client.get(f"/api/regulations/{rid}/text/versions").get_json()
    edited = next(v for v in versions if v["meta"].get("edited"))
    assert "Pasal 99" in client.get(f"/api/regulations/{rid}/text/versions/{edited['id']}").get_json()["text"]
    client.post(f"/api/regulations/{rid}/text/versions/{edited['id']}/restore")
    restored = client.get(f"/api/regulations/{rid}/analysis").get_json()
    assert restored["text"]["edited"]
    assert "Pasal 99" in client.get(f"/api/regulations/{rid}/text").get_json()["content"]


@needs_tesseract
def test_scan_mode_on_text_pdf_explains_what_to_do(client):
    rid = reg_id(client)
    upload(client, rid, make_pdf([TEXT.splitlines()[:30]]))
    client.post(f"/api/regulations/{rid}/ocr", json={"mode": "scan"})
    job = wait(client, rid)
    assert job["status"] == "error" and "Semua halaman" in job["message"]
