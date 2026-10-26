import pytest

from app import create_app
from app.auth import _FAILS, create_user
from app.db import get_db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    _FAILS.clear()
    return create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True, "SEED_ON_START": False})


def login(c, email, pw="rahasia123"):
    return c.post("/api/auth/login", json={"email": email, "password": pw})


def add_users(app):
    with app.app_context():
        for role in ("admin", "editor", "viewer"):
            create_user(get_db(), f"{role}@example.com", role.title(), "rahasia123", role)


def test_requires_login(app):
    c = app.test_client()
    assert c.get("/api/dashboard").status_code == 401
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert c.get("/login").status_code == 200
    assert c.get("/healthz").get_json() == {"ok": True}


def test_first_run_setup_then_locked(app):
    c = app.test_client()
    assert c.get("/api/auth/status").get_json()["setup_required"] is True
    r = c.post("/api/auth/setup", json={"email": "a@x.co", "name": "A", "password": "rahasia123"})
    assert r.status_code == 201 and r.get_json()["user"]["role"] == "admin"
    assert c.get("/api/dashboard").status_code == 200
    other = app.test_client()
    assert other.post("/api/auth/setup", json={"email": "b@x.co", "password": "rahasia123"}).status_code == 403


def test_setup_disabled_when_env_admin_required(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "t.db"), "SEED_ON_START": False, "REQUIRE_ENV_ADMIN": True})
    c = app.test_client()
    assert c.get("/api/auth/status").get_json()["setup_required"] is False
    assert c.post("/api/auth/setup", json={"email": "b@x.co", "password": "rahasia123"}).status_code == 403


def test_bootstrap_admin_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "Boss@Example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "superrahasia")
    app = create_app({"DATABASE": str(tmp_path / "t.db"), "SEED_ON_START": False})
    c = app.test_client()
    assert login(c, "boss@example.com", "superrahasia").get_json()["user"]["role"] == "admin"


def test_wrong_password_and_throttle(app):
    add_users(app)
    c = app.test_client()
    for _ in range(10):
        assert login(c, "admin@example.com", "salah").status_code == 401
    assert login(c, "admin@example.com").status_code == 429


def test_role_permissions(app):
    add_users(app)
    v, e, a = app.test_client(), app.test_client(), app.test_client()
    login(v, "viewer@example.com"), login(e, "editor@example.com"), login(a, "admin@example.com")
    reg = a.post("/api/regulations", json={"jenis": "PP", "nomor": "1", "tahun": 2020, "judul": "Uji"})
    assert reg.status_code == 201
    rid = a.get("/api/regulations?category=Lainnya").get_json()[0]["id"]

    assert v.get(f"/api/regulations/{rid}").status_code == 200
    assert v.get("/api/export.csv").status_code == 200
    assert v.patch(f"/api/regulations/{rid}", json={"relevance": "relevan"}).status_code == 403
    assert e.patch(f"/api/regulations/{rid}", json={"relevance": "relevan"}).status_code == 200

    assert e.patch("/api/sources/1", json={"enabled": False}).status_code == 403
    assert a.patch("/api/sources/1", json={"enabled": False}).status_code == 200
    assert e.get("/api/users").status_code == 403
    assert a.get("/api/users").status_code == 200
    assert v.post("/api/auth/password", json={"current": "rahasia123", "new": "barubaru1"}).status_code == 200
    assert login(app.test_client(), "viewer@example.com", "barubaru1").status_code == 200


def test_user_management(app):
    add_users(app)
    a = app.test_client()
    me = login(a, "admin@example.com").get_json()["user"]
    r = a.post("/api/users", json={"email": "baru@example.com", "name": "Baru", "password": "rahasia123", "role": "editor"})
    assert r.status_code == 201
    uid = r.get_json()["id"]
    assert a.post("/api/users", json={"email": "baru@example.com", "password": "rahasia123"}).status_code == 400
    assert a.post("/api/users", json={"email": "x@example.com", "password": "pendek"}).status_code == 400
    assert a.patch(f"/api/users/{me['id']}", json={"active": False}).status_code == 400
    assert a.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 400

    a.patch(f"/api/users/{uid}", json={"active": False})
    assert login(app.test_client(), "baru@example.com").status_code == 401


def test_deactivated_user_session_ends(app):
    add_users(app)
    a, e = app.test_client(), app.test_client()
    login(a, "admin@example.com"), login(e, "editor@example.com")
    assert e.get("/api/dashboard").status_code == 200
    eid = next(u["id"] for u in a.get("/api/users").get_json() if u["role"] == "editor")
    a.patch(f"/api/users/{eid}", json={"active": False})
    assert e.get("/api/dashboard").status_code == 401
