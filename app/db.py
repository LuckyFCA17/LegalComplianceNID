"""SQLite storage for the compliance register."""
import getpass
import glob
import os
import socket
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- bpk | kemnaker | jdihn | seed
    base_url    TEXT,
    config      TEXT DEFAULT '{}',       -- JSON: keywords, feed url, page limit
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_sync   TEXT,
    last_status TEXT,
    last_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS regulations (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER REFERENCES sources(id),
    reg_key         TEXT UNIQUE NOT NULL, -- normalised "jenis|nomor|tahun"
    jenis           TEXT NOT NULL,        -- UU, PP, Permenaker, ...
    nomor           TEXT NOT NULL,
    tahun           INTEGER,
    judul           TEXT NOT NULL,        -- "tentang ..."
    status_berlaku  TEXT NOT NULL DEFAULT 'Berlaku', -- Berlaku | Diubah | Dicabut
    url             TEXT,                 -- the regulation's own page on a JDIH site
    pdf_url         TEXT,                 -- official PDF of the regulation
    detail_checked_at TEXT,               -- last time the detail page was read / looked up
    category        TEXT NOT NULL DEFAULT 'Lainnya',
    category_locked INTEGER NOT NULL DEFAULT 0, -- 1 = set manually, sync won't overwrite
    relevance       TEXT NOT NULL DEFAULT 'pending', -- pending | relevan | tidak_relevan
    relevance_note  TEXT,
    suggested       TEXT DEFAULT '[]',    -- JSON list of suggested obligations
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reg_category ON regulations(category);
CREATE INDEX IF NOT EXISTS ix_reg_relevance ON regulations(relevance);

CREATE TABLE IF NOT EXISTS obligations (
    id            INTEGER PRIMARY KEY,
    regulation_id INTEGER NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
    pasal         TEXT,
    description   TEXT NOT NULL,
    pic           TEXT,
    due_date      TEXT,
    status        TEXT NOT NULL DEFAULT 'belum', -- belum | proses | terpenuhi | tidak_berlaku
    evidence      TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obl_reg ON obligations(regulation_id);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL COLLATE NOCASE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer', -- admin | editor | viewer
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY,
    source_id  INTEGER REFERENCES sources(id),
    started_at TEXT NOT NULL,
    status     TEXT NOT NULL,
    fetched    INTEGER DEFAULT 0,
    inserted   INTEGER DEFAULT 0,
    updated    INTEGER DEFAULT 0,
    message    TEXT
);

-- Regulation categories, editable in the app (K3, Lingkungan, ... plus user-defined ones).
CREATE TABLE IF NOT EXISTS categories (
    id               INTEGER PRIMARY KEY,
    name             TEXT UNIQUE NOT NULL COLLATE NOCASE,
    search_keywords  TEXT NOT NULL DEFAULT '[]', -- JSON list: terms searched on JDIH sites
    title_keywords   TEXT NOT NULL DEFAULT '[]', -- JSON list: terms that put a title in this category
    position         INTEGER NOT NULL DEFAULT 0,
    builtin          INTEGER NOT NULL DEFAULT 0, -- 1 = shipped with the app
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- Full text of a regulation (from its PDF, an uploaded file or pasted text) for analysis and search.
CREATE TABLE IF NOT EXISTS regulation_texts (
    regulation_id INTEGER PRIMARY KEY REFERENCES regulations(id) ON DELETE CASCADE,
    origin        TEXT NOT NULL,           -- pdf_url | upload | paste
    filename      TEXT,
    pages         INTEGER,
    scanned       INTEGER NOT NULL DEFAULT 0, -- 1 = little or no text layer (scan); needs OCR elsewhere
    text          TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    fetched_by    TEXT
);

-- Cross-process locks (e.g. only one computer may run a sync on a shared database).
CREATE TABLE IF NOT EXISTS locks (
    name        TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,
    acquired_at TEXT NOT NULL
);
"""

# Server installs use WAL (fast, several workers on one machine). A database on a network share
# (portable mode) must use the classic rollback journal: WAL needs shared memory on one computer.
SETTINGS = {"journal_mode": "WAL", "busy_timeout": 15}


def configure(journal_mode=None, busy_timeout=None):
    if journal_mode:
        SETTINGS["journal_mode"] = journal_mode.upper()
    if busy_timeout:
        SETTINGS["busy_timeout"] = float(busy_timeout)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(path, timeout=SETTINGS["busy_timeout"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


MIGRATIONS = [
    # (table, column, DDL) — columns added after the first release
    ("regulations", "pdf_url", "ALTER TABLE regulations ADD COLUMN pdf_url TEXT"),
    ("regulations", "detail_checked_at", "ALTER TABLE regulations ADD COLUMN detail_checked_at TEXT"),
]


def migrate(conn):
    for table, column, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(ddl)
    # v1 stored BPK *search* URLs for catalogue entries; they are not the regulation's own page.
    conn.execute("UPDATE regulations SET url = NULL WHERE url LIKE '%/Search?keywords=%'")
    # v1 pointed the Kemnaker source at a non-existent catalogue URL with only 2 pages.
    # Kemnaker now searches by keyword (pages via "hal"), so fewer pages per keyword are needed.
    conn.execute("UPDATE sources SET config = '{\"max_pages\": 5}' "
                 "WHERE code = 'kemnaker' AND config IN ('{\"max_pages\": 2}', '{\"max_pages\": 15}')")


def init_db(conn):
    conn.execute(f"PRAGMA journal_mode = {SETTINGS['journal_mode']}")
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.commit()


def integrity_ok(conn):
    """Quick structural check of the database file (returns (ok, message))."""
    rows = [r[0] for r in conn.execute("PRAGMA quick_check(5)")]
    return rows == ["ok"], "; ".join(rows)


# ---------------------------------------------------------------- locks
def whoami():
    try:
        user = getpass.getuser()
    except Exception:  # no user name available (e.g. some services)
        user = "?"
    return f"{socket.gethostname()} ({user})"


def acquire_lock(conn, name, holder, stale_after=timedelta(minutes=30)):
    """Take a named lock stored in the database. Returns None on success, else the current holder row.

    A lock older than stale_after is considered abandoned (computer crashed or was switched off).
    """
    stale = (datetime.now(timezone.utc) - stale_after).isoformat(timespec="seconds")
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")  # serialise lock takers across processes / computers
    try:
        conn.execute("DELETE FROM locks WHERE name = ? AND acquired_at < ?", (name, stale))
        row = conn.execute("SELECT * FROM locks WHERE name = ?", (name,)).fetchone()
        if row is not None and row["holder"] != holder:
            conn.execute("ROLLBACK")
            return row
        conn.execute("INSERT OR REPLACE INTO locks (name, holder, acquired_at) VALUES (?,?,?)", (name, holder, now()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return None


def release_lock(conn, name, holder):
    conn.execute("DELETE FROM locks WHERE name = ? AND holder = ?", (name, holder))
    conn.commit()


# ---------------------------------------------------------------- backups
def backup_database(conn, db_path, keep=10):
    """Copy the database (consistent snapshot) to backups/compliance-YYYYmmdd-HHMMSS.db next to it."""
    folder = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(folder, f"compliance-{stamp}.db")
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    old = sorted(glob.glob(os.path.join(folder, "compliance-*.db")))[:-keep]
    for path in old:
        try:
            os.remove(path)
        except OSError:
            pass
    return target
