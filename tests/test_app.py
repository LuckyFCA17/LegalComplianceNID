import io
import json

import pytest

from app import create_app
from app.connectors.base import Connector
from app.connectors.html_search import parse_results
from app.connectors.jdihn import parse_feed
from app.db import connect
from app.legal import classify, parse_citation, reg_key
from app.sync import run_sync


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True})


@pytest.fixture
def client(app):
    """A client logged in as admin."""
    c = app.test_client()
    with app.app_context():
        from app.auth import create_user
        from app.db import get_db
        create_user(get_db(), "admin@example.com", "Admin", "rahasia123", "admin")
    assert c.post("/api/auth/login", json={"email": "admin@example.com", "password": "rahasia123"}).status_code == 200
    return c


def _find(client, judul):
    regs = client.get("/api/regulations?category=K3,Lingkungan,Ketenagakerjaan,Lainnya").get_json()
    return next(r for r in regs if r["judul"] == judul)


# ---------------------------------------------------------------- parsing
def test_parse_citation_variants():
    p = parse_citation("Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018 tentang Keselamatan dan "
                       "Kesehatan Kerja Lingkungan Kerja")
    assert p == {"jenis": "Permenaker", "nomor": "5", "tahun": 2018,
                 "judul": "Keselamatan dan Kesehatan Kerja Lingkungan Kerja"}
    assert parse_citation("Peraturan Pemerintah (PP) Nomor 22 Tahun 2021")["jenis"] == "PP"
    assert parse_citation("Undang-undang No. 1 Tahun 1970 tentang Keselamatan Kerja")["jenis"] == "UU"
    assert parse_citation("Peraturan Menteri Tenaga Kerja dan Transmigrasi Nomor PER.08/MEN/VII/2010 "
                          "Tahun 2010")["nomor"] == "PER.08/MEN/VII/2010"
    assert parse_citation("Berita terbaru") is None


def test_reg_key_normalises_jenis():
    assert reg_key("Peraturan Menteri Ketenagakerjaan", "5", 2018) == reg_key("Permenaker", " 5", 2018)


@pytest.mark.parametrize("judul,expected", [
    ("Keselamatan dan Kesehatan Kerja Listrik di Tempat Kerja", "K3"),
    ("Pengelolaan Limbah Bahan Berbahaya dan Beracun", "Lingkungan"),
    ("Baku Mutu Air Limbah", "Lingkungan"),
    ("Pengupahan", "Ketenagakerjaan"),
    ("Tunjangan Hari Raya Keagamaan bagi Pekerja/Buruh di Perusahaan", "Ketenagakerjaan"),
    ("Pajak Daerah dan Retribusi Daerah", "Lainnya"),
])
def test_classify(judul, expected):
    assert classify(judul) == expected


BPK_HTML = """
<html><body><div class="row">
 <div class="card mb-3"><div class="card-body">
   <a href="/Details/88008/permenaker-no-5-tahun-2018">Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018</a>
   <div>Keselamatan dan Kesehatan Kerja Lingkungan Kerja</div>
   <span class="badge">Berlaku</span>
 </div></div>
 <div class="card mb-3"><div class="card-body">
   <a href="/Details/5468/pp-no-101-tahun-2014">PP No. 101 Tahun 2014</a>
   <p>tentang Pengelolaan Limbah Bahan Berbahaya dan Beracun</p>
   <span class="badge">Dicabut</span>
 </div></div>
 <a href="/Home/About">Tentang kami</a>
</div></body></html>
"""


def test_parse_bpk_results():
    recs = parse_results(BPK_HTML, "https://peraturan.bpk.go.id/Search?keywords=x", r"/Details/\d+")
    assert len(recs) == 2
    a, b = recs
    assert (a["jenis"], a["nomor"], a["tahun"], a["status_berlaku"]) == ("Permenaker", "5", 2018, "Berlaku")
    assert a["judul"] == "Keselamatan dan Kesehatan Kerja Lingkungan Kerja"
    assert a["url"] == "https://peraturan.bpk.go.id/Details/88008/permenaker-no-5-tahun-2018"
    assert (b["jenis"], b["status_berlaku"]) == ("PP", "Dicabut")
    assert b["judul"] == "Pengelolaan Limbah Bahan Berbahaya dan Beracun"


def test_parse_jdihn_feed():
    feed = {"data": [
        {"idData": "1", "jenis": "Peraturan Pemerintah", "noPeraturan": "50", "tahun_pengundangan": "2012",
         "judul": "Peraturan Pemerintah Nomor 50 Tahun 2012 tentang Penerapan SMK3", "status": "Berlaku",
         "urlDetailPeraturan": "https://example.go.id/1"},
        {"judul": "Undang-Undang Nomor 13 Tahun 2003 tentang Ketenagakerjaan", "status": "Diubah"},
        {"judul": "tanpa nomor"},
    ]}
    recs = parse_feed(feed)
    assert [(r["jenis"], r["nomor"], r["tahun"]) for r in recs] == [("PP", "50", 2012), ("UU", "13", 2003)]
    assert recs[0]["judul"] == "Penerapan SMK3"
    assert recs[1]["status_berlaku"] == "Diubah"


# ---------------------------------------------------------------- workflow
def test_seed_loaded_and_categorised(client):
    regs = client.get("/api/regulations?category=K3").get_json()
    assert any(r["citation"] == "UU No. 1 Tahun 1970" for r in regs)
    assert all(r["category"] == "K3" for r in regs)


def test_mark_relevant_creates_suggested_obligations(client):
    reg = _find(client, "Keselamatan Kerja")
    r = client.patch(f"/api/regulations/{reg['id']}", json={"relevance": "relevan"}).get_json()
    assert r["relevance"] == "relevan"
    assert len(r["obligations"]) == len(reg["suggested"]) > 0
    # Marking relevant again must not duplicate obligations.
    r = client.patch(f"/api/regulations/{reg['id']}", json={"relevance": "relevan"}).get_json()
    assert len(r["obligations"]) == len(reg["suggested"])


def test_dashboard_compliance_pct(client):
    reg = _find(client, "Keselamatan Kerja")
    obls = client.patch(f"/api/regulations/{reg['id']}", json={"relevance": "relevan"}).get_json()["obligations"]
    n = len(obls)
    client.patch(f"/api/obligations/{obls[0]['id']}", json={"status": "terpenuhi"})
    client.patch(f"/api/obligations/{obls[1]['id']}", json={"status": "tidak_berlaku"})
    client.patch(f"/api/obligations/{obls[2]['id']}", json={"status": "proses", "due_date": "2000-01-01"})
    d = client.get("/api/dashboard?category=K3").get_json()
    k3 = d["per_category"][0]
    assert k3["obligation_total"] == n
    assert k3["compliance_pct"] == round(100 / (n - 1), 1)
    assert d["summary"]["overdue"] == 1
    assert d["overdue"][0]["id"] == obls[2]["id"]


def test_invalid_inputs_rejected(client):
    reg = _find(client, "Keselamatan Kerja")
    assert client.patch(f"/api/regulations/{reg['id']}", json={"relevance": "x"}).status_code == 400
    obl = client.post(f"/api/regulations/{reg['id']}/obligations", json={"description": "Uji"}).get_json()
    assert client.patch(f"/api/obligations/{obl['id']}", json={"due_date": "31-12-2026"}).status_code == 400
    assert client.patch(f"/api/obligations/{obl['id']}", json={"status": "done"}).status_code == 400


class FakeConnector(Connector):
    def __init__(self, records):
        super().__init__()
        self.records = records

    def fetch(self, categories=None):
        yield from self.records


def test_sync_updates_status_but_keeps_user_decisions(app, client):
    reg = _find(client, "Keselamatan Kerja")
    client.patch(f"/api/regulations/{reg['id']}", json={"relevance": "relevan", "relevance_note": "pabrik"})
    client.patch(f"/api/regulations/{reg['id']}", json={"category": "Lainnya"})

    from app.connectors.base import make_record
    conn = connect(app.config["DATABASE"])
    src = conn.execute("SELECT * FROM sources WHERE code='bpk'").fetchone()
    res = run_sync(conn, src, connector=FakeConnector([
        make_record("Undang-Undang", "1", 1970, "Keselamatan Kerja", status="Diubah"),
        make_record("Permenaker", "99", 2030, "Keselamatan dan Kesehatan Kerja Baru", status=None),
    ]))
    conn.close()
    assert (res["status"], res["inserted"], res["updated"]) == ("ok", 1, 1)

    r = client.get(f"/api/regulations/{reg['id']}").get_json()
    assert r["status_berlaku"] == "Diubah"
    assert (r["relevance"], r["relevance_note"], r["category"]) == ("relevan", "pabrik", "Lainnya")
    d = client.get("/api/dashboard?category=Lainnya").get_json()
    assert [x["id"] for x in d["review_needed"]] == [reg["id"]]


def test_sync_connector_error_is_logged(app, client):
    from app.connectors.base import ConnectorError

    class Broken(Connector):
        def fetch(self, categories=None):
            raise ConnectorError("blocked")
            yield

    conn = connect(app.config["DATABASE"])
    src = conn.execute("SELECT * FROM sources WHERE code='kemnaker'").fetchone()
    res = run_sync(conn, src, connector=Broken())
    conn.close()
    assert res["status"] == "error"
    assert client.get("/api/sync/log").get_json()[0]["message"] == "blocked"


def test_import_csv_and_export(client):
    csv_data = ("jenis,nomor,tahun,judul,status,category\n"
                "Perda,3,2022,Pengendalian Pencemaran Udara,Berlaku,\n"
                "Permenaker,1,2024,Uji Coba,Berlaku,K3\n")
    r = client.post("/api/import", data={"file": (io.BytesIO(csv_data.encode()), "regs.csv")},
                    content_type="multipart/form-data").get_json()
    assert (r["fetched"], r["inserted"]) == (2, 2)
    perda = _find(client, "Pengendalian Pencemaran Udara")
    assert perda["category"] == "Lingkungan"
    assert _find(client, "Uji Coba")["category"] == "K3"

    client.patch(f"/api/regulations/{perda['id']}", json={"relevance": "relevan"})
    client.post(f"/api/regulations/{perda['id']}/obligations", json={"description": "Uji emisi cerobong"})
    out = client.get("/api/export.csv?category=Lingkungan").get_data(as_text=True)
    assert "Uji emisi cerobong" in out and "Perda No. 3 Tahun 2022" in out


def test_spa_served(client):
    assert b"Legal Compliance" in client.get("/").data
    assert json.loads(client.get("/api/meta").data)["categories"][0] == "K3"


def test_filter_and_sort_by_assessment_and_compliance(client):
    regs = client.get("/api/regulations?category=K3").get_json()
    by = {r["citation"]: r["id"] for r in regs}
    done, partial, notyet, empty = (by["UU No. 1 Tahun 1970"], by["Permenaker No. 5 Tahun 2018"],
                                    by["Permenaker No. 8 Tahun 2020"], by["PP No. 88 Tahun 2019"])
    for rid in (done, partial, notyet, empty):
        client.patch(f"/api/regulations/{rid}", json={"relevance": "relevan"})
    client.patch(f"/api/regulations/{by['Permenaker No. 6 Tahun 2017']}", json={"relevance": "tidak_relevan"})
    for o in client.get(f"/api/regulations/{empty}").get_json()["obligations"]:
        client.delete(f"/api/obligations/{o['id']}")
    for o in client.get(f"/api/regulations/{done}").get_json()["obligations"]:
        client.patch(f"/api/obligations/{o['id']}", json={"status": "terpenuhi"})
    first = client.get(f"/api/regulations/{partial}").get_json()["obligations"][0]
    client.patch(f"/api/obligations/{first['id']}", json={"status": "proses", "due_date": "2000-01-01"})

    def ids(qs):
        return {r["id"] for r in client.get("/api/regulations?category=K3&" + qs).get_json()}

    assert ids("relevance=relevan") == {done, partial, notyet, empty}
    assert ids("relevance=tidak_relevan") == {by["Permenaker No. 6 Tahun 2017"]}
    assert len(ids("relevance=pending")) == len(regs) - 5
    assert ids("compliance=terpenuhi") == {done}
    assert ids("compliance=proses") == {partial}
    assert ids("compliance=belum") == {notyet}
    assert ids("compliance=tanpa_kewajiban") == {empty}
    assert ids("compliance=terlambat") == {partial}
    assert ids("compliance=terpenuhi&relevance=pending") == set()

    rows = client.get("/api/regulations?category=K3&sort=pemenuhan_desc").get_json()
    assert [r["compliance_pct"] for r in rows[:3]] == [100.0, 0.0, 0.0]
    assert rows[0]["id"] == done and {rows[1]["id"], rows[2]["id"]} == {partial, notyet}
    assert all(r["compliance_pct"] is None for r in rows[3:])  # unscored regulations last
    asc = client.get("/api/regulations?category=K3&sort=pemenuhan_asc").get_json()
    assert [r["compliance_pct"] for r in asc[:3]] == [0.0, 0.0, 100.0]
    years = [r["tahun"] for r in client.get("/api/regulations?category=K3&sort=tahun_desc").get_json()]
    assert years == sorted(years, reverse=True)
    titles = [r["judul"].lower() for r in client.get("/api/regulations?category=K3&sort=judul").get_json()]
    assert titles == sorted(titles)


@pytest.mark.parametrize("q,expected", [
    ("50", ["PP No. 50 Tahun 2012"]),
    ("PP 50", ["PP No. 50 Tahun 2012"]),
    ("nomor 50", ["PP No. 50 Tahun 2012"]),
    ("PP No. 50 Tahun 2012", ["PP No. 50 Tahun 2012"]),
    ("peraturan pemerintah nomor 50", ["PP No. 50 Tahun 2012"]),
    ("5/2018", ["Permenaker No. 5 Tahun 2018"]),
    ("No.5 Tahun 2018", ["Permenaker No. 5 Tahun 2018"]),
    ("Permenaker 5 2018", ["Permenaker No. 5 Tahun 2018"]),
    ("peraturan menteri ketenagakerjaan nomor 5 tahun 2018", ["Permenaker No. 5 Tahun 2018"]),
    ("UU 1 1970", ["UU No. 1 Tahun 1970"]),
    ("5", ["Permenaker No. 5 Tahun 2018", "Permen LH No. 5 Tahun 2014"]),  # not No. 15 / 50 / 51
    ("permenaker 2018", ["Permenaker No. 5 Tahun 2018"]),
    ("limbah domestik", ["Permen LHK No. 68 Tahun 2016"]),
    ("PP 50 2099", []),
])
def test_search_by_number_type_year_and_title(client, q, expected):
    rows = client.get("/api/regulations", query_string={
        "category": "K3,Lingkungan,Ketenagakerjaan,Lainnya", "q": q}).get_json()
    assert sorted(r["citation"] for r in rows) == sorted(expected)


def test_search_matches_composite_numbers_and_ranks_exact_number_first(client):
    client.post("/api/regulations", json={"jenis": "Permenaker", "nomor": "PER.07/MEN/1999", "tahun": 1999,
                                          "judul": "Panitia Pembina K3"})
    client.post("/api/regulations", json={"jenis": "PP", "nomor": "7", "tahun": 1999, "judul": "Uji urutan"})
    for q in ("PER.07/MEN/1999", "per.07", "permenaker 07 1999"):
        rows = client.get("/api/regulations", query_string={"category": "K3,Lainnya", "q": q}).get_json()
        assert "Permenaker No. PER.07/MEN/1999 Tahun 1999" in [r["citation"] for r in rows], q
    rows = client.get("/api/regulations", query_string={"category": "K3,Lainnya", "q": "7 1999"}).get_json()
    assert [r["citation"] for r in rows] == ["PP No. 7 Tahun 1999", "Permenaker No. PER.07/MEN/1999 Tahun 1999"]
