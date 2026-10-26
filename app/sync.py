"""Synchronise regulation sources into the local register."""
import json

from .connectors import get_connector
from .connectors.base import ConnectorError
from .db import now
from .legal import classify, reg_key

DEFAULT_SOURCES = [
    {
        "code": "seed", "name": "Katalog Awal (offline)", "kind": "seed", "base_url": None,
        "config": {},
    },
    {
        "code": "bpk", "name": "JDIH BPK RI", "kind": "bpk", "base_url": "https://peraturan.bpk.go.id",
        "config": {"max_pages": 2},
    },
    {
        "code": "kemnaker", "name": "JDIH Kemnaker", "kind": "kemnaker",
        "base_url": "https://jdih.kemnaker.go.id", "config": {"max_pages": 2},
    },
    {
        "code": "jdihn", "name": "Feed JDIHN (JSON)", "kind": "jdihn", "base_url": None,
        "config": {"feed_url": ""}, "enabled": 0,
    },
]


def ensure_sources(conn):
    for s in DEFAULT_SOURCES:
        conn.execute(
            "INSERT OR IGNORE INTO sources (code, name, kind, base_url, config, enabled) VALUES (?,?,?,?,?,?)",
            (s["code"], s["name"], s["kind"], s["base_url"], json.dumps(s["config"]), s.get("enabled", 1)),
        )
    conn.commit()


def upsert_regulation(conn, rec, source_id):
    """Insert or update one normalised record. Returns 'inserted', 'updated' or 'unchanged'.

    Sync never touches user decisions: relevance, notes and manually locked categories
    are preserved; only bibliographic fields and the legal status are refreshed.
    """
    key = reg_key(rec["jenis"], rec["nomor"], rec["tahun"])
    ts = now()
    row = conn.execute("SELECT * FROM regulations WHERE reg_key = ?", (key,)).fetchone()
    suggested = json.dumps(rec.get("suggested") or [])
    if row is None:
        conn.execute(
            """INSERT INTO regulations (source_id, reg_key, jenis, nomor, tahun, judul, status_berlaku,
               url, category, suggested, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, key, rec["jenis"], rec["nomor"], rec["tahun"], rec["judul"], rec["status_berlaku"],
             rec.get("url"), rec.get("category") or classify(rec["judul"], rec["jenis"]), suggested, ts, ts),
        )
        return "inserted"

    changes = {}
    if rec["status_berlaku"] != row["status_berlaku"] and rec.get("status_explicit", True):
        changes["status_berlaku"] = rec["status_berlaku"]
    if rec.get("url") and not row["url"]:
        changes["url"] = rec["url"]
    if rec["judul"] and len(rec["judul"]) > len(row["judul"] or ""):
        changes["judul"] = rec["judul"]
    if rec.get("suggested") and row["suggested"] in (None, "", "[]"):
        changes["suggested"] = suggested
    if not row["category_locked"]:
        cat = rec.get("category") or classify(changes.get("judul", row["judul"]), row["jenis"])
        if cat != row["category"]:
            changes["category"] = cat
    if not changes:
        return "unchanged"
    changes["updated_at"] = ts
    cols = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(f"UPDATE regulations SET {cols} WHERE id = ?", (*changes.values(), row["id"]))
    return "updated"


def run_sync(conn, source, categories=None, connector=None):
    """Fetch from one source row and store results. Returns a summary dict."""
    started = now()
    stats = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0}
    status, message = "ok", ""
    try:
        conn_obj = connector or get_connector(source["kind"], source["base_url"],
                                              json.loads(source["config"] or "{}"))
        for rec in conn_obj.fetch(categories):
            stats["fetched"] += 1
            if categories and rec.get("category") is None:
                if classify(rec["judul"], rec["jenis"]) not in categories:
                    continue
            stats[upsert_regulation(conn, rec, source["id"])] += 1
    except ConnectorError as exc:
        status, message = "error", str(exc)
    except Exception as exc:  # keep the app alive on unexpected markup / parsing errors
        status, message = "error", f"{type(exc).__name__}: {exc}"
    if status == "ok":
        message = (f"{stats['fetched']} ditemukan, {stats['inserted']} baru, "
                   f"{stats['updated']} diperbarui")
    conn.execute(
        "INSERT INTO sync_log (source_id, started_at, status, fetched, inserted, updated, message) "
        "VALUES (?,?,?,?,?,?,?)",
        (source["id"], started, status, stats["fetched"], stats["inserted"], stats["updated"], message),
    )
    conn.execute(
        "UPDATE sources SET last_sync = ?, last_status = ?, last_count = ? WHERE id = ?",
        (started, f"{status}: {message}", stats["inserted"] + stats["updated"], source["id"]),
    )
    conn.commit()
    return {"source": source["code"], "status": status, "message": message, **stats}


def apply_suggestions(conn, regulation_id):
    """Create obligations from a regulation's suggested list if it has none yet."""
    row = conn.execute("SELECT suggested FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
    if row is None:
        return 0
    existing = conn.execute("SELECT COUNT(*) FROM obligations WHERE regulation_id = ?",
                            (regulation_id,)).fetchone()[0]
    if existing:
        return 0
    items = json.loads(row["suggested"] or "[]")
    ts = now()
    for it in items:
        conn.execute(
            "INSERT INTO obligations (regulation_id, pasal, description, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (regulation_id, it.get("pasal") or "", it["description"], "belum", ts, ts),
        )
    return len(items)
