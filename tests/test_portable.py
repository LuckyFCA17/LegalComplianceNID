"""Portable mode: one database on a shared folder, used by several computers at once."""
import glob
import os
import sqlite3
import threading
import time

import pytest

import launcher
from app import create_app
from app import db as dbmod
from app.auth import create_user
from app.connectors.base import Connector
from app.sync import SyncBusy, run_sync_job


@pytest.fixture(autouse=True)
def restore_db_settings():
    saved = dict(dbmod.SETTINGS)
    yield
    dbmod.SETTINGS.update(saved)


def portable_app(path, monkeypatch):
    monkeypatch.setenv("LCN_PORTABLE", "1")
    return create_app({"DATABASE": str(path), "TESTING": True})


def login_editor(app):
    with app.app_context():
        from app.db import get_db
        if not get_db().execute("SELECT 1 FROM users WHERE email = 'e@x.co'").fetchone():
            create_user(get_db(), "e@x.co", "E", "rahasia123", "editor")
    c = app.test_client()
    c.post("/api/auth/login", json={"email": "e@x.co", "password": "rahasia123"})
    return c


def test_portable_mode_uses_network_safe_settings(tmp_path, monkeypatch):
    app = portable_app(tmp_path / "data" / "compliance.db", monkeypatch)
    assert app.config["PORTABLE"] and app.config["BACKUP_BEFORE_SYNC"]
    conn = sqlite3.connect(tmp_path / "data" / "compliance.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # no WAL on a network share
    assert not glob.glob(str(tmp_path / "data" / "*-wal"))
    meta = login_editor(app).get("/api/meta").get_json()
    assert meta["portable"] and meta["database"].endswith("compliance.db")


def test_server_mode_keeps_wal(tmp_path):
    create_app({"DATABASE": str(tmp_path / "c.db"), "TESTING": True})
    assert sqlite3.connect(tmp_path / "c.db").execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_sync_makes_backup_first_and_keeps_last_ten(tmp_path, monkeypatch):
    app = portable_app(tmp_path / "compliance.db", monkeypatch)
    c = login_editor(app)
    seed = next(s for s in c.get("/api/sources").get_json() if s["code"] == "seed")
    for _ in range(12):
        res = c.post("/api/sync", json={"source_ids": [seed["id"]]}).get_json()
        time.sleep(1.01)  # backups are named per second
    assert res[0]["backup"].startswith(str(tmp_path / "backups"))
    backups = sorted(glob.glob(str(tmp_path / "backups" / "compliance-*.db")))
    assert len(backups) == 10
    copy = sqlite3.connect(backups[-1])
    assert copy.execute("SELECT COUNT(*) FROM regulations").fetchone()[0] == 42
    assert copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"


class SlowConnector(Connector):
    def __init__(self, started):
        super().__init__()
        self.started = started

    def fetch(self, categories=None):
        self.started.set()
        time.sleep(1.5)
        return iter(())


def test_only_one_computer_can_sync_at_a_time(tmp_path, monkeypatch):
    path = tmp_path / "compliance.db"
    app = portable_app(path, monkeypatch)
    started = threading.Event()
    monkeypatch.setattr("app.sync.get_connector", lambda *a, **k: SlowConnector(started))
    # "Computer A" syncs (own connection, own machine name) ...
    monkeypatch.setattr("app.sync.whoami", lambda: "PC-HSE-01 (budi)")
    src = dbmod.connect(str(path)).execute("SELECT * FROM sources WHERE code = 'bpk'").fetchone()

    def computer_a():
        run_sync_job(dbmod.connect(str(path)), [src])  # its own connection, like a separate PC
    t = threading.Thread(target=computer_a, daemon=True)
    t.start()
    assert started.wait(5)
    # ... while "computer B" presses Sinkronkan in the browser.
    monkeypatch.setattr("app.sync.whoami", lambda: "PC-LEGAL-02 (sari)")
    r = login_editor(app).post("/api/sync", json={"source_ids": [src["id"]]})
    assert r.status_code == 409
    assert "PC-HSE-01 (budi)" in r.get_json()["error"]
    t.join(5)
    # Lock released once A is done: B can sync now.
    r = login_editor(app).post("/api/sync", json={"source_ids": [src["id"]]})
    assert r.status_code == 200


def test_abandoned_lock_expires(tmp_path, monkeypatch):
    path = tmp_path / "compliance.db"
    portable_app(path, monkeypatch)
    conn = dbmod.connect(str(path))
    conn.execute("INSERT INTO locks (name, holder, acquired_at) VALUES ('sync', 'PC-MATI (x)', '2020-01-01T00:00:00+00:00')")
    conn.commit()
    assert dbmod.acquire_lock(conn, "sync", "PC-BARU (y)") is None  # crashed computer does not block forever
    with pytest.raises(SyncBusy):
        run_sync_job(dbmod.connect(str(path)), [], None)  # held by PC-BARU, so another holder is refused


def test_lock_released_when_sync_crashes(tmp_path, monkeypatch):
    path = tmp_path / "compliance.db"
    portable_app(path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("putus")
    monkeypatch.setattr("app.sync.run_sync", boom)
    conn = dbmod.connect(str(path))
    with pytest.raises(RuntimeError):
        run_sync_job(conn, [object()], None)
    assert conn.execute("SELECT COUNT(*) FROM locks").fetchone()[0] == 0


def test_two_computers_opening_a_new_database_at_once(tmp_path, monkeypatch):
    path = tmp_path / "compliance.db"
    monkeypatch.setenv("LCN_PORTABLE", "1")
    errors = []

    def open_app():
        try:
            create_app({"DATABASE": str(path), "TESTING": True})
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=open_app) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM regulations").fetchone()[0] == 42


def test_launcher_data_location_and_integrity_check(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LCN_DATA_DIR", raising=False)
    monkeypatch.setattr(launcher, "base_dir", lambda: str(tmp_path))
    assert launcher.data_dir() == os.path.join(str(tmp_path), "data")
    (tmp_path / "data-location.txt").write_text("# folder bersama\n\\\\server\\compliance\\data\n", encoding="utf-8")
    assert launcher.data_dir() == "\\\\server\\compliance\\data"

    good = tmp_path / "good.db"
    sqlite3.connect(good).execute("CREATE TABLE t (x)")
    assert launcher.check_integrity(str(good))
    assert launcher.check_integrity(str(tmp_path / "belum-ada.db"))
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
    assert not launcher.check_integrity(str(bad))
    assert "DATABASE RUSAK" in capsys.readouterr().out
