"""Connector parsing, detail/PDF enrichment and migration — with a fake HTTP layer."""
import sqlite3

import pytest
import requests

from app import create_app
from app.connectors import base as base_mod
from app.connectors.html_search import BpkConnector, KemnakerConnector, parse_detail, parse_results
from app.db import connect, init_db
from app.sync import run_sync

BPK = "https://peraturan.bpk.go.id"
KEM = "https://jdih.kemnaker.go.id"

BPK_SEARCH = """
<div class="row">
 <div class="card"><div class="card-body">
  <a href="/Details/145520/permenaker-no-6-tahun-2017">Peraturan Menteri Ketenagakerjaan Nomor 6 Tahun 2017</a>
  <p>Keselamatan dan Kesehatan Kerja Elevator dan Eskalator</p>
  <span class="badge">Berlaku</span>
  <small>Tanggal Berlaku: 3 Maret 2017</small>
 </div></div>
 <div class="card"><div class="card-body">
  <a href="/Details/145984/permenaker-no-12-tahun-2015">Permenaker No. 12 Tahun 2015</a>
  <p>tentang Keselamatan dan Kesehatan Kerja Listrik di Tempat Kerja</p>
  <span class="badge">Diubah</span>
  <a href="/Download/28437/Permenaker%2012%20Tahun%202015.pdf">Download</a>
 </div></div>
</div>"""

BPK_DETAIL = """
<html><body><nav><a href="/Home">Beranda</a> Berlaku</nav>
<h4>Peraturan Menteri Ketenagakerjaan Nomor 6 Tahun 2017</h4>
<table>
 <tr><th>Judul</th><td>Peraturan Menteri Ketenagakerjaan Nomor 6 Tahun 2017 tentang Keselamatan dan Kesehatan
   Kerja Elevator dan Eskalator</td></tr>
 <tr><th>Tanggal Berlaku</th><td>3 Maret 2017</td></tr>
 <tr><th>Status</th><td>Tidak Berlaku</td></tr>
</table>
<div>Mencabut: Permenaker No. 3 Tahun 1999</div>
<a class="btn" href="/Download/30115/Permenaker%20Nomor%206%20Tahun%202017.pdf">Unduh</a>
</body></html>"""

KEM_LIST = """
<div class="list-group">
 <div class="item">
  <h5><a href="https://jdih.kemnaker.go.id/peraturan/detail/1546/peraturan-menteri-ketenagakerjaan-nomor-5-tahun-2018">
   Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018</a></h5>
  <p>Keselamatan dan Kesehatan Kerja Lingkungan Kerja</p><span class="label">Berlaku</span>
 </div>
 <div class="item">
  <h5><a href="/peraturan/detail/88/peraturan-menteri-nomor-4-tahun-1987">Peraturan Menteri Tenaga Kerja Nomor
   PER.04/MEN/1987 Tahun 1987</a></h5>
  <p>Panitia Pembina Keselamatan dan Kesehatan Kerja</p><span class="label">Tidak Berlaku</span>
 </div>
 <a href="/peraturan?page=2">2</a>
</div>"""

KEM_DETAIL = """
<div class="detail">
 <dl><dt>Status</dt><dd>Berlaku</dd><dt>Tentang</dt><dd>Keselamatan dan Kesehatan Kerja Lingkungan Kerja</dd></dl>
 <iframe src="https://jdih.kemnaker.go.id/asset/data_puu/2018pmnaker005.pdf"></iframe>
</div>"""


class FakeResponse:
    def __init__(self, url, text, status=200):
        self.url, self.text, self.status_code = url, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    """Routes URLs (by prefix) to canned pages; records every request."""
    pages = {}
    calls = []

    def __init__(self):
        self.headers = {}

    def get(self, url, timeout=None, **kw):
        FakeSession.calls.append(url)
        for prefix, (status, text) in sorted(self.pages.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                return FakeResponse(url, text, status)
        return FakeResponse(url, "<html></html>", 404)


@pytest.fixture
def fake_http(monkeypatch):
    FakeSession.pages, FakeSession.calls = {}, []
    monkeypatch.setattr(base_mod.requests, "Session", FakeSession)
    return FakeSession


# ---------------------------------------------------------------- parsing
def test_bpk_results_have_detail_pages_and_pdf():
    recs = parse_results(BPK_SEARCH, BPK + "/Search?keywords=k3", r"/Details/\d+")
    assert [r["url"] for r in recs] == [BPK + "/Details/145520/permenaker-no-6-tahun-2017",
                                       BPK + "/Details/145984/permenaker-no-12-tahun-2015"]
    assert recs[0]["status_berlaku"] == "Berlaku"  # "Tanggal Berlaku" is not mistaken for a status
    assert recs[0]["pdf_url"] is None
    assert recs[1]["pdf_url"] == BPK + "/Download/28437/Permenaker%2012%20Tahun%202015.pdf"
    assert recs[1]["status_berlaku"] == "Diubah"


def test_bpk_detail_page():
    d = parse_detail(BPK_DETAIL, BPK + "/Details/145520/x")
    assert d["pdf_url"] == BPK + "/Download/30115/Permenaker%20Nomor%206%20Tahun%202017.pdf"
    assert d["status"] == "Dicabut"  # "Tidak Berlaku" label wins over nav text / "Mencabut"
    assert d["judul"] == "Keselamatan dan Kesehatan Kerja Elevator dan Eskalator"


def test_kemnaker_listing_and_detail():
    recs = parse_results(KEM_LIST, KEM + "/peraturan?page=1", r"/peraturan/detail/\d+")
    assert [(r["jenis"], r["nomor"], r["tahun"], r["status_berlaku"]) for r in recs] == [
        ("Permenaker", "5", 2018, "Berlaku"), ("Permenaker", "PER.04/MEN/1987", 1987, "Dicabut")]
    assert recs[1]["url"] == KEM + "/peraturan/detail/88/peraturan-menteri-nomor-4-tahun-1987"
    d = parse_detail(KEM_DETAIL, recs[0]["url"])
    assert d == {"pdf_url": KEM + "/asset/data_puu/2018pmnaker005.pdf", "status": "Berlaku",
                 "judul": "Keselamatan dan Kesehatan Kerja Lingkungan Kerja"}


def test_kemnaker_searches_catalogue_with_hal_pages(fake_http):
    fake_http.pages = {KEM + "/peraturan?hal=1&keyword=k3&": (200, KEM_LIST),
                       KEM + "/peraturan?hal=2&keyword=k3&": (200, "<p>kosong</p>")}
    c = KemnakerConnector(KEM, {"keywords": ["k3"], "max_pages": 5, "delay": 0})
    recs = list(c.fetch(["K3"]))
    assert len(recs) == 2
    assert fake_http.calls == [KEM + "/",  # warm-up visit for cookies
                               KEM + "/peraturan?hal=1&keyword=k3&nomor=&sort=terbaru&status=&tahun=",
                               KEM + "/peraturan?hal=2&keyword=k3&nomor=&sort=terbaru&status=&tahun="]
    assert c.errors == []


def test_pagination_stops_when_site_repeats_page(fake_http):
    fake_http.pages = {KEM + "/peraturan?hal=": (200, KEM_LIST)}  # every page identical
    c = KemnakerConnector(KEM, {"keywords": ["k3"], "max_pages": 5, "delay": 0})
    assert len(list(c.fetch())) == 2
    assert len([u for u in fake_http.calls if "hal=" in u]) == 2


def test_kemnaker_lookup_filters_by_nomor_and_tahun(fake_http):
    page = """<div class="item"><a href="peraturan/detail/1588/peraturan-presiden-nomor-7-tahun-2019">Detail</a>
              <p>Penyakit Akibat Kerja</p><span class="badge">Berlaku</span></div>"""
    fake_http.pages = {KEM + "/peraturan?hal=1&keyword=&nomor=7&sort=terbaru&status=&tahun=2019": (200, page)}
    rec = KemnakerConnector(KEM, {"delay": 0}).lookup("Perpres", "7", 2019)
    assert rec["url"] == KEM + "/peraturan/detail/1588/peraturan-presiden-nomor-7-tahun-2019"
    assert (rec["jenis"], rec["judul"], rec["status_berlaku"]) == ("Perpres", "Penyakit Akibat Kerja", "Berlaku")


def test_citation_from_slug_when_card_text_is_unhelpful():
    html = """<div class="card"><a href="/Details/218299/permenkes-no-11-tahun-2022">Lihat</a>
              <p>Pelayanan Kesehatan Penyakit Akibat Kerja</p></div>"""
    [rec] = parse_results(html, BPK + "/Search?keywords=x", BpkConnector.default_link_pattern)
    assert (rec["jenis"], rec["nomor"], rec["tahun"]) == ("Permenkes", "11", 2022)
    assert rec["judul"] == "Pelayanan Kesehatan Penyakit Akibat Kerja"


def test_ssl_fallback_for_incomplete_certificate_chain(fake_http, monkeypatch):
    def get(self, url, timeout=None, verify=True, **kw):
        FakeSession.calls.append((url, verify))
        if verify:
            raise requests.exceptions.SSLError("unable to get local issuer certificate")
        return FakeResponse(url, KEM_LIST)
    monkeypatch.setattr(FakeSession, "get", get)
    c = KemnakerConnector(KEM, {"keywords": ["k3"], "max_pages": 1, "delay": 0})
    assert len(list(c.fetch())) == 2
    assert "tanpa verifikasi SSL" in c.notes[0]

    strict = KemnakerConnector(KEM, {"keywords": ["k3"], "max_pages": 1, "delay": 0, "ssl_fallback": False})
    assert list(strict.fetch()) == []
    assert "sertifikat SSL ditolak" in strict.errors[0]


def test_http_errors_are_explained(fake_http):
    fake_http.pages = {BPK: (403, "blocked")}
    c = BpkConnector(BPK, {"keywords": ["k3"], "delay": 0})
    assert list(c.fetch()) == []
    assert "HTTP 403" in c.errors[0] and "proteksi bot" in c.errors[0]


# ---------------------------------------------------------------- sync + enrichment
@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True})


def _reg(conn, jenis, nomor, tahun):
    return conn.execute("SELECT * FROM regulations WHERE jenis = ? AND nomor = ? AND tahun = ?",
                        (jenis, nomor, tahun)).fetchone()


def test_bpk_sync_links_catalogue_entries_to_pages_and_pdfs(app, fake_http):
    lookup_page = """<div class="card"><a href="/Details/5/pp-no-50-tahun-2012">Peraturan Pemerintah Nomor 50
        Tahun 2012</a><p>Penerapan Sistem Manajemen Keselamatan dan Kesehatan Kerja</p><span class="badge">Berlaku</span>
        </div>"""
    fake_http.pages = {
        BPK + "/Search?keywords=k3": (200, BPK_SEARCH),
        BPK + "/Search?keywords=PP+No.+50+Tahun+2012": (200, lookup_page),
        BPK + "/Details/145520/": (200, BPK_DETAIL),
        BPK + "/Details/218299/": (200, '<p>Status</p><p>Berlaku</p>'
                                        '<a href="/Download/212692/Permenkes%20Nomor%2011%20Tahun%202022.pdf">Unduh</a>'),
        BPK + "/Details/5/": (200, '<a href="/Download/5/PP%2050%202012.pdf">PDF</a><p>Status</p><p>Berlaku</p>'),
        BPK + "/Search": (200, "<p>Tidak ada hasil</p>"),
    }
    conn = connect(app.config["DATABASE"])
    conn.execute("UPDATE sources SET config = ? WHERE code = 'bpk'",
                 ('{"keywords": ["k3"], "max_pages": 1, "delay": 0, "lookup_limit": 50}',))
    res = run_sync(conn, conn.execute("SELECT * FROM sources WHERE code = 'bpk'").fetchone(), ["K3"])
    assert res["status"] == "ok", res["message"]

    elevator = _reg(conn, "Permenaker", "6", 2017)
    assert elevator["url"] == BPK + "/Details/145520/permenaker-no-6-tahun-2017"
    assert elevator["pdf_url"].endswith("/Download/30115/Permenaker%20Nomor%206%20Tahun%202017.pdf")
    assert elevator["status_berlaku"] == "Dicabut"  # detail page status refines the list badge
    listrik = _reg(conn, "Permenaker", "12", 2015)
    assert listrik["pdf_url"].endswith("Permenaker%2012%20Tahun%202015.pdf")

    pak = _reg(conn, "Permenkes", "11", 2022)  # catalogue entry with a known page: PDF id differs from page id
    assert pak["pdf_url"] == BPK + "/Download/212692/Permenkes%20Nomor%2011%20Tahun%202022.pdf"
    smk3 = _reg(conn, "PP", "50", 2012)  # catalogue entry without a page: found by citation lookup
    assert smk3["url"] == BPK + "/Details/5/pp-no-50-tahun-2012"
    assert smk3["pdf_url"] == BPK + "/Download/5/PP%2050%202012.pdf"
    assert res["linked"] >= 1 and res["details"] >= 1

    # Entries looked up without success are not searched again on the next run.
    before = len(fake_http.calls)
    run_sync(conn, conn.execute("SELECT * FROM sources WHERE code = 'bpk'").fetchone(), ["K3"])
    repeated = [u for u in fake_http.calls[before:] if "No.+50+Tahun+2012" in u]
    assert repeated == []
    conn.close()


def test_sync_reports_error_when_site_blocks(app, fake_http):
    fake_http.pages = {BPK: (403, "blocked")}
    conn = connect(app.config["DATABASE"])
    conn.execute("UPDATE sources SET config = '{\"delay\": 0}' WHERE code = 'bpk'")
    res = run_sync(conn, conn.execute("SELECT * FROM sources WHERE code = 'bpk'").fetchone(), ["K3"])
    conn.close()
    assert res["status"] == "error"
    assert "HTTP 403" in res["message"]
    # Stops after a few consecutive failures instead of trying every regulation.
    assert len(fake_http.calls) < 15


def test_detail_endpoint_and_manual_links(app, fake_http):
    from app.auth import create_user
    from app.db import get_db
    with app.app_context():
        create_user(get_db(), "e@x.co", "E", "rahasia123", "editor")
    c = app.test_client()
    c.post("/api/auth/login", json={"email": "e@x.co", "password": "rahasia123"})
    regs = c.get("/api/regulations?category=K3").get_json()
    k3 = next(r for r in regs if r["citation"] == "Permenaker No. 5 Tahun 2018")
    assert k3["url"].startswith(KEM + "/peraturan/detail/1546/")
    assert "Search?keywords=Permenaker+nomor+5+tahun+2018" in k3["search_url"]

    fake_http.pages = {KEM + "/peraturan/detail/1546/": (200, KEM_DETAIL)}
    r = c.post(f"/api/regulations/{k3['id']}/detail").get_json()
    assert r["pdf_url"] == KEM + "/asset/data_puu/2018pmnaker005.pdf"
    assert r["message"] == "Halaman peraturan dan PDF ditemukan"

    other = next(r for r in regs if r["citation"] == "PP No. 88 Tahun 2019")
    assert c.patch(f"/api/regulations/{other['id']}", json={"pdf_url": "javascript:alert(1)"}).status_code == 400
    r = c.patch(f"/api/regulations/{other['id']}", json={"url": "https://contoh.go.id/pp88", "pdf_url": "https://contoh.go.id/pp88.pdf"})
    assert r.get_json()["pdf_url"] == "https://contoh.go.id/pp88.pdf"


def test_migration_from_v1_database(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE sources (id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            kind TEXT NOT NULL, base_url TEXT, config TEXT DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
            last_sync TEXT, last_status TEXT, last_count INTEGER DEFAULT 0);
        INSERT INTO sources (code, name, kind, base_url, config) VALUES
            ('kemnaker', 'JDIH Kemnaker', 'kemnaker', 'https://jdih.kemnaker.go.id', '{"max_pages": 2}');
        CREATE TABLE regulations (id INTEGER PRIMARY KEY, source_id INTEGER, reg_key TEXT UNIQUE NOT NULL,
            jenis TEXT NOT NULL, nomor TEXT NOT NULL, tahun INTEGER, judul TEXT NOT NULL,
            status_berlaku TEXT NOT NULL DEFAULT 'Berlaku', url TEXT, category TEXT NOT NULL DEFAULT 'Lainnya',
            category_locked INTEGER NOT NULL DEFAULT 0, relevance TEXT NOT NULL DEFAULT 'pending',
            relevance_note TEXT, suggested TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO regulations (reg_key, jenis, nomor, tahun, judul, url, created_at, updated_at) VALUES
            ('uu|1|1970', 'UU', '1', 1970, 'Keselamatan Kerja',
             'https://peraturan.bpk.go.id/Search?keywords=Keselamatan+Kerja', 'x', 'x');
    """)
    old.commit()
    old.close()
    conn = connect(path)
    init_db(conn)
    row = conn.execute("SELECT url, pdf_url, detail_checked_at FROM regulations").fetchone()
    assert tuple(row) == (None, None, None)
    assert conn.execute("SELECT config FROM sources WHERE code='kemnaker'").fetchone()[0] == '{"max_pages": 5}'
    conn.close()


def test_source_connection_test_endpoint(app, fake_http):
    from app.auth import create_user
    from app.db import get_db
    with app.app_context():
        create_user(get_db(), "e@x.co", "E", "rahasia123", "editor")
    c = app.test_client()
    c.post("/api/auth/login", json={"email": "e@x.co", "password": "rahasia123"})
    sid = next(s["id"] for s in c.get("/api/sources").get_json() if s["code"] == "bpk")
    c.patch(f"/api/sources/{sid}", json={"config": {"delay": 0}})  # editor may not change config
    fake_http.pages = {BPK + "/Search?keywords=k3": (200, BPK_SEARCH), BPK + "/Details/145520/": (200, BPK_DETAIL)}
    t = c.post(f"/api/sources/{sid}/test", json={"keyword": "k3"}).get_json()
    assert t["ok"] and t["found"] == 2 and t["matching_links"] == 2
    assert t["detail"]["pdf_url"].endswith("Permenaker%20Nomor%206%20Tahun%202017.pdf")

    fake_http.pages = {BPK: (403, "blocked")}
    t = c.post(f"/api/sources/{sid}/test", json={"keyword": "k3"}).get_json()
    assert not t["ok"] and "HTTP 403" in t["error"]
