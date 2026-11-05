"""Offline legal analysis: PDF text, articles, requirement candidates, applying them, searching text."""
import io
import os

import pytest

from app import create_app
from app.analysis import AnalysisError, analyze, clean_text, extract_pdf, split_articles
from app.auth import create_user
from app.db import get_db

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "contoh_peraturan.txt")


def make_pdf(pages):
    """Minimal text PDF (Helvetica), one list of lines per page — enough for pypdf to extract."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
        stream = "BT /F1 9 Tf 40 800 Td 11 TL " + " ".join(f"({t}) Tj T*" for t in esc) + " ET"
        objs.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        content_no = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {content_no} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def fixture_lines():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read().splitlines()


def fixture_pdf():
    lines = fixture_lines()
    return make_pdf([lines[:22], lines[22:]])


# ---------------------------------------------------------------- engine
def test_pdf_extraction_and_cleaning():
    text, pages, scanned = extract_pdf(fixture_pdf())
    assert pages == 2 and not scanned
    assert "www.peraturan.go.id" not in text and "- 5 -" not in text  # page furniture removed
    assert "perusahaannya" in text  # hyphenated line break re-joined
    with pytest.raises(AnalysisError):
        extract_pdf(b"<html>not a pdf</html>")


def test_scanned_pdf_is_flagged():
    _text, _pages, scanned = extract_pdf(make_pdf([[""], [""]]))
    assert scanned


def test_articles_skip_elucidation():
    arts = split_articles(clean_text(open(FIXTURE).read()))
    assert [a["pasal"] for a in arts] == ["Pasal 1", "Pasal 5", "Pasal 9", "Pasal 12", "Pasal 13", "Pasal 16",
                                          "Pasal 19"]
    assert [u["ayat"] for u in arts[1]["units"]] == ["1", "2"]
    # "ayat (1)" inside a sentence is a reference, not a new ayat
    assert len(arts[-1]["units"]) == 1


def test_requirement_candidates():
    r = analyze(clean_text(open(FIXTURE).read()))
    by = {c["pasal"]: c for c in r["candidates"]}
    assert not any(p == "Pasal 1" or p.startswith("Pasal 1 ") for p in by)  # definitions are not requirements
    smk3 = by["Pasal 5 ayat (1)"]
    assert (smk3["type"], smk3["party"], smk3["confidence"]) == ("kewajiban", "perusahaan", "tinggi")
    assert smk3["description"] == "Menerapkan SMK3 di perusahaannya."
    assert smk3["sanction"] == ["Pasal 19"] and "100 (seratus) orang" in smk3["context"]
    lapor = by["Pasal 9 ayat (1)"]
    assert lapor["type"] == "pelaporan" and lapor["timing"] == "paling lambat 30 (tiga puluh) hari kerja"
    gov = by["Pasal 9 ayat (2)"]
    assert gov["party"] == "pemerintah" and not gov["suggested"]  # government duty: unticked
    assert by["Pasal 12"]["type"] == "larangan" and by["Pasal 12"]["sanction"] == ["Pasal 19"]
    assert by["Pasal 13"]["type"] == "perizinan"
    audit = by["Pasal 16 ayat (1)"]
    assert audit["description"] == "Audit SMK3 dilakukan secara berkala setiap 3 (tiga) tahun."
    assert audit["timing"] == "setiap 3 (tiga) tahun"
    assert r["sanctions"][0]["refers_to"] == ["Pasal 12", "Pasal 5"]
    assert r["counts"] == {"kewajiban": 3, "pelaporan": 1, "larangan": 1, "perizinan": 1}


# ---------------------------------------------------------------- API
@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True})


def login(app, role):
    with app.app_context():
        create_user(get_db(), f"{role}@x.co", role.title(), "rahasia123", role)
    c = app.test_client()
    c.post("/api/auth/login", json={"email": f"{role}@x.co", "password": "rahasia123"})
    return c


def pp50(c):
    return c.get("/api/regulations?category=K3&q=PP 50 2012").get_json()[0]["id"]


def test_upload_analyse_and_apply(app):
    c = login(app, "editor")
    rid = pp50(c)
    assert c.get(f"/api/regulations/{rid}/analysis").get_json()["text"] is None
    r = c.post(f"/api/regulations/{rid}/text/upload",
               data={"file": (io.BytesIO(fixture_pdf()), "pp50.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    a = r.get_json()
    assert a["text"]["pages"] == 2 and a["text"]["origin"] == "upload" and a["text"]["fetched_by"] == "Editor"
    assert a["articles"] == 7 and len(a["candidates"]) == 6

    picks = [x for x in a["candidates"] if x["suggested"]]
    body = {"items": [{"pasal": x["pasal"], "description": x["description"],
                       "notes": f"Sanksi: {', '.join(x['sanction'])}" if x["sanction"] else ""} for x in picks]}
    assert c.post(f"/api/regulations/{rid}/analysis/apply", json=body).get_json() == {"added": 5, "skipped": 0}
    assert c.post(f"/api/regulations/{rid}/analysis/apply", json=body).get_json()["added"] == 0  # no duplicates
    obls = c.get(f"/api/regulations/{rid}").get_json()["obligations"]
    added = next(o for o in obls if o["pasal"] == "Pasal 5 ayat (1)")
    assert added["description"] == "Menerapkan SMK3 di perusahaannya." and added["notes"] == "Sanksi: Pasal 19"
    again = c.get(f"/api/regulations/{rid}/analysis").get_json()
    assert all(x["added"] for x in again["candidates"] if x["suggested"])


def test_paste_text_viewer_rights_and_delete(app):
    editor, viewer = login(app, "editor"), login(app, "viewer")
    rid = pp50(editor)
    assert viewer.post(f"/api/regulations/{rid}/text", json={"text": open(FIXTURE).read()}).status_code == 403
    assert editor.post(f"/api/regulations/{rid}/text", json={"text": "terlalu pendek"}).status_code == 400
    r = editor.post(f"/api/regulations/{rid}/text", json={"text": open(FIXTURE).read()}).get_json()
    assert r["text"]["origin"] == "paste" and len(r["candidates"]) == 6
    assert viewer.get(f"/api/regulations/{rid}/analysis").status_code == 200  # everyone may read
    assert "Pasal 5" in viewer.get(f"/api/regulations/{rid}/text").get_json()["content"]
    assert editor.delete(f"/api/regulations/{rid}/text").status_code == 204
    assert editor.get(f"/api/regulations/{rid}/analysis").get_json()["text"] is None


def test_fetch_pdf_from_official_link(app, monkeypatch):
    c = login(app, "editor")
    rid = pp50(c)
    assert c.post(f"/api/regulations/{rid}/text/fetch").status_code == 400  # no PDF link yet
    c.patch(f"/api/regulations/{rid}", json={"pdf_url": "https://peraturan.bpk.go.id/Download/5/PP%2050%202012.pdf"})
    pdf = fixture_pdf()

    class Resp:
        status_code = 200

        def __init__(self, body):
            self.content, self.text = body, ""

        def raise_for_status(self):
            pass
    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: Resp(pdf if url.endswith(".pdf") else b""))
    r = c.post(f"/api/regulations/{rid}/text/fetch").get_json()
    assert r["text"]["origin"] == "pdf_url" and r["text"]["filename"] == "PP%2050%202012.pdf"

    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: Resp(b"<html>login</html>"))
    r = c.post(f"/api/regulations/{rid}/text/fetch")
    assert r.status_code == 400 and "bukan" in r.get_json()["error"].lower() or "tidak mengarah" in r.get_json()["error"]


def test_search_inside_regulation_text(app):
    c = login(app, "editor")
    rid = pp50(c)
    c.post(f"/api/regulations/{rid}/text", json={"text": open(FIXTURE).read()})
    q = "audit independen"
    plain = c.get("/api/regulations", query_string={"category": "K3", "q": q}).get_json()
    assert all(r["id"] != rid for r in plain)  # title search does not see the body
    deep = c.get("/api/regulations", query_string={"category": "K3", "q": q, "in_text": "1"}).get_json()
    hit = next(r for r in deep if r["id"] == rid)
    assert hit["has_text"] and "lembaga audit independen" in hit["text_snippet"]
