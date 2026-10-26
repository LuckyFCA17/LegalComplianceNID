"""SQLite storage for the compliance register."""
import sqlite3
from datetime import datetime, timezone

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
    url             TEXT,
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
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(path)
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


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()
