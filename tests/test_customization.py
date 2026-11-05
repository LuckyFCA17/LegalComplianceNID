"""Custom categories, search keywords and sync sources."""
import pytest

from app import create_app
from app.auth import create_user
from app.connectors.base import Connector, make_record
from app.db import connect, get_db
from app.sync import run_sync


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True})


def client_as(app, role):
    with app.app_context():
        create_user(get_db(), f"{role}@x.co", role, "rahasia123", role)
    c = app.test_client()
    c.post("/api/auth/login", json={"email": f"{role}@x.co", "password": "rahasia123"})
    return c


@pytest.fixture
def admin(app):
    return client_as(app, "admin")


def cat(admin, name):
    return next(c for c in admin.get("/api/categories").get_json() if c["name"] == name)


# ---------------------------------------------------------------- categories
def test_builtin_categories_with_keywords(admin):
    cats = admin.get("/api/categories").get_json()
    assert [c["name"] for c in cats] == ["K3", "Lingkungan", "Ketenagakerjaan", "Lainnya"]
    k3 = cats[0]
    assert "SMK3" in k3["search_keywords"] and "smk3" in k3["title_keywords"]
    assert k3["regulations"] > 0 and cats[-1]["fallback"]
    meta = admin.get("/api/meta").get_json()
    assert meta["categories"] == ["K3", "Lingkungan", "Ketenagakerjaan", "Lainnya"]
    assert "AMDAL" in meta["search_keywords"]["Lingkungan"]


def test_add_category_is_used_everywhere(admin):
    r = admin.post("/api/categories", json={"name": "Energi & Kelistrikan",
                                            "search_keywords": "ketenagalistrikan, energi\nmigas"})
    assert r.status_code == 201
    new = r.get_json()
    assert new["search_keywords"] == ["ketenagalistrikan", "energi", "migas"]
    assert new["title_keywords"] == new["search_keywords"]  # defaults to the search terms
    meta = admin.get("/api/meta").get_json()
    assert meta["categories"][-2:] == ["Energi & Kelistrikan", "Lainnya"]  # fallback stays last

    # Manual entry, filtering, dashboard and moving a regulation all accept the new category.
    admin.post("/api/regulations", json={"jenis": "UU", "nomor": "30", "tahun": 2009,
                                         "judul": "Ketenagalistrikan"})
    regs = admin.get("/api/regulations?category=Energi %26 Kelistrikan").get_json()
    assert [r["citation"] for r in regs] == ["UU No. 30 Tahun 2009"]  # auto-classified by title
    dash = admin.get("/api/dashboard?category=Energi %26 Kelistrikan").get_json()
    assert dash["per_category"][0]["regulations"] == 1
    rid = admin.get("/api/regulations?category=K3").get_json()[0]["id"]
    assert admin.patch(f"/api/regulations/{rid}", json={"category": "Energi & Kelistrikan"}).status_code == 200


def test_category_validation(admin):
    assert admin.post("/api/categories", json={"name": "k3"}).status_code == 400  # duplicate, any case
    assert admin.post("/api/categories", json={"name": ""}).status_code == 400
    assert admin.post("/api/categories", json={"name": "x" * 41}).status_code == 400
    assert admin.post("/api/categories", json={"name": "Ok", "search_keywords": ["a" * 81]}).status_code == 400
    lainnya = cat(admin, "Lainnya")
    assert admin.patch(f"/api/categories/{lainnya['id']}", json={"name": "Umum"}).status_code == 400
    assert admin.delete(f"/api/categories/{lainnya['id']}").status_code == 400
    assert admin.patch("/api/categories/999", json={"name": "Z"}).status_code == 404


def test_rename_and_delete_keep_regulations(admin):
    k3 = cat(admin, "K3")
    n = k3["regulations"]
    rid = admin.get("/api/regulations?category=K3").get_json()[0]["id"]
    admin.patch(f"/api/regulations/{rid}", json={"relevance": "relevan"})
    r = admin.patch(f"/api/categories/{k3['id']}", json={"name": "K3 & Kesehatan"})
    assert r.get_json()["name"] == "K3 & Kesehatan"
    assert len(admin.get("/api/regulations?category=K3 %26 Kesehatan").get_json()) == n
    assert admin.get(f"/api/regulations/{rid}").get_json()["relevance"] == "relevan"

    r = admin.delete(f"/api/categories/{k3['id']}").get_json()
    assert r["moved_to_fallback"] == n
    reg = admin.get(f"/api/regulations/{rid}").get_json()
    assert (reg["category"], reg["relevance"]) == ("Lainnya", "relevan")  # assessment is kept


def test_edit_title_keywords_and_reclassify(admin):
    admin.post("/api/regulations", json={"jenis": "PP", "nomor": "5", "tahun": 2021,
                                         "judul": "Penyelenggaraan Perizinan Berusaha Berbasis Risiko"})
    pp5 = admin.get("/api/regulations?category=Lainnya&q=PP 5 2021").get_json()[0]
    assert pp5["category"] == "Lainnya"
    admin.post("/api/categories", json={"name": "Perizinan", "search_keywords": "perizinan berusaha",
                                        "title_keywords": "perizinan"})
    # A category picked by hand is never moved by reclassification.
    locked = admin.get("/api/regulations?category=K3").get_json()[0]
    admin.patch(f"/api/regulations/{locked['id']}", json={"category": "Lainnya"})

    preview = admin.post("/api/categories/reclassify", json={"dry_run": True}).get_json()
    assert preview["changes"].get("Lainnya → Perizinan") == 1
    assert admin.get(f"/api/regulations/{pp5['id']}").get_json()["category"] == "Lainnya"  # dry run
    admin.post("/api/categories/reclassify", json={})
    assert admin.get(f"/api/regulations/{pp5['id']}").get_json()["category"] == "Perizinan"
    assert admin.get(f"/api/regulations/{locked['id']}").get_json()["category"] == "Lainnya"


def test_only_admin_changes_categories_and_sources(app, admin):
    editor = client_as(app, "editor")
    assert editor.get("/api/categories").status_code == 200
    assert editor.post("/api/categories", json={"name": "X"}).status_code == 403
    k3 = cat(admin, "K3")
    assert editor.patch(f"/api/categories/{k3['id']}", json={"search_keywords": "x"}).status_code == 403
    assert editor.post("/api/sources", json={"kind": "jdihn", "name": "X",
                                             "config": {"feed_url": "https://x.go.id/f"}}).status_code == 403
    assert editor.delete("/api/sources/1").status_code == 403


# ---------------------------------------------------------------- search keywords
class RecordingConnector(Connector):
    searched = []

    def fetch(self, categories=None):
        RecordingConnector.searched = self.keywords(categories)
        yield make_record("Permen ESDM", "10", 2021, "Keselamatan Ketenagalistrikan Pembangkit", status="Berlaku")


def test_sync_uses_edited_keywords_and_categories(app, admin):
    k3 = cat(admin, "K3")
    admin.patch(f"/api/categories/{k3['id']}", json={"search_keywords": "keselamatan kerja\nK3 listrik"})
    admin.post("/api/categories", json={"name": "Energi", "search_keywords": "ketenagalistrikan",
                                        "title_keywords": "ketenagalistrikan, pembangkit"})
    conn = connect(app.config["DATABASE"])
    src = conn.execute("SELECT * FROM sources WHERE code = 'bpk'").fetchone()
    run_sync(conn, src, ["K3", "Energi"], connector=RecordingConnector())
    assert RecordingConnector.searched == ["keselamatan kerja", "K3 listrik", "ketenagalistrikan"]
    row = conn.execute("SELECT category FROM regulations WHERE nomor = '10' AND tahun = 2021").fetchone()
    assert row["category"] == "Energi"  # classified with the new category's title keywords
    conn.close()


def test_per_source_keyword_override_still_wins(admin):
    bpk = next(s for s in admin.get("/api/sources").get_json() if s["code"] == "bpk")
    r = admin.patch(f"/api/sources/{bpk['id']}", json={"config": {"max_pages": 1, "keywords": "smk3, apar"}})
    assert next(s for s in r.get_json() if s["code"] == "bpk")["config"]["keywords"] == ["smk3", "apar"]


# ---------------------------------------------------------------- custom sources
HTML_SOURCE = {
    "kind": "html", "name": "JDIH KLHK", "base_url": "https://jdih.menlhk.go.id/",
    "config": {"search_url": "{base}/peraturan?cari={q}&halaman={page}", "link_pattern": r"peraturan/detail/\d+",
               "max_pages": "3"},
}


def test_add_custom_html_source_and_sync_it(app, admin, monkeypatch):
    r = admin.post("/api/sources", json=HTML_SOURCE)
    assert r.status_code == 201, r.get_json()
    src = r.get_json()
    assert src["code"] == "custom-jdih-klhk" and src["enabled"] == 1
    assert src["base_url"] == "https://jdih.menlhk.go.id" and src["config"]["max_pages"] == 3
    assert admin.post("/api/sources", json=HTML_SOURCE).get_json()["code"] == "custom-jdih-klhk-2"

    page = """<div class="item"><a href="/peraturan/detail/77/permen-lhk-nomor-6-tahun-2021">Peraturan Menteri
      Lingkungan Hidup dan Kehutanan Nomor 6 Tahun 2021</a><p>Tata Cara dan Persyaratan Pengelolaan Limbah B3</p>
      <span class="badge">Berlaku</span></div>"""
    calls = []

    class Resp:
        status_code, text = 200, page

        def raise_for_status(self):
            pass

    def fake_get(self, url, **kw):
        calls.append(url)
        return Resp()
    monkeypatch.setattr("requests.Session.get", fake_get)
    res = admin.post("/api/sync", json={"source_ids": [src["id"]], "categories": ["Lingkungan"]}).get_json()
    assert res[0]["status"] in ("ok", "partial"), res
    assert any("cari=limbah&halaman=1" in u for u in calls)
    reg = admin.get("/api/regulations?category=Lingkungan&q=Permen LHK 6 2021").get_json()[0]
    assert reg["url"] == "https://jdih.menlhk.go.id/peraturan/detail/77/permen-lhk-nomor-6-tahun-2021"

    t = admin.post(f"/api/sources/{src['id']}/test", json={"keyword": "limbah"}).get_json()
    assert t["ok"] and t["found"] == 1


@pytest.mark.parametrize("change,message", [
    ({"kind": "ftp"}, "Jenis sumber"),
    ({"name": ""}, "Nama sumber"),
    ({"base_url": "jdih.menlhk.go.id"}, "URL dasar"),
    ({"config": {"link_pattern": "x"}}, "search_url wajib"),
    ({"config": {"search_url": "{base}/cari?q={q}", "link_pattern": "x"}}, "{page}"),
    ({"config": {"search_url": "{base}/cari?q={kata}&p={page}", "link_pattern": "x"}}, "placeholder"),
    ({"config": {"search_url": "{base}/c?q={q}&p={page}", "link_pattern": "detail/(\\d+"}}, "regex"),
    ({"config": {"search_url": "{base}/c?q={q}&p={page}", "link_pattern": "d", "max_pages": 99}}, "max_pages"),
])
def test_custom_source_validation(admin, change, message):
    body = {**HTML_SOURCE, **change}
    r = admin.post("/api/sources", json=body)
    assert r.status_code == 400 and message in r.get_json()["error"], r.get_json()


def test_add_feed_source_test_and_delete(app, admin, monkeypatch):
    assert admin.post("/api/sources", json={"kind": "jdihn", "name": "JDIH Provinsi",
                                            "config": {}}).status_code == 400  # feed_url required
    src = admin.post("/api/sources", json={"kind": "jdihn", "name": "JDIH Provinsi",
                                           "config": {"feed_url": "https://jdih.prov.go.id/integrasi"}}).get_json()

    class Resp:
        status_code, text = 200, "[]"

        def raise_for_status(self):
            pass

        def json(self):
            return [{"jenis": "Peraturan Daerah", "noPeraturan": "3", "tahun_pengundangan": "2022",
                     "judul": "Pengendalian Pencemaran Udara", "status": "Berlaku"}]
    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: Resp())
    t = admin.post(f"/api/sources/{src['id']}/test", json={}).get_json()
    assert t["ok"] and t["samples"][0]["citation"] == "Perda No. 3 Tahun 2022"
    admin.post("/api/sync", json={"source_ids": [src["id"]]})
    assert admin.get("/api/regulations?q=Perda 3 2022&category=Lingkungan").get_json()

    r = admin.delete(f"/api/sources/{src['id']}").get_json()
    assert r["regulations_kept"] == 1
    assert admin.get("/api/regulations?q=Perda 3 2022&category=Lingkungan").get_json()  # data stays
    assert all(s["id"] != src["id"] for s in admin.get("/api/sources").get_json())
    bpk = next(s for s in admin.get("/api/sources").get_json() if s["code"] == "bpk")
    assert admin.delete(f"/api/sources/{bpk['id']}").status_code == 400  # built-in: disable instead
