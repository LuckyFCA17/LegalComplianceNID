"""Synchronise regulation sources into the local register."""
import json
from datetime import datetime, timedelta, timezone

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
        "base_url": "https://jdih.kemnaker.go.id", "config": {"max_pages": 15},
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
               url, pdf_url, category, suggested, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, key, rec["jenis"], rec["nomor"], rec["tahun"], rec["judul"], rec["status_berlaku"],
             rec.get("url"), rec.get("pdf_url"), rec.get("category") or classify(rec["judul"], rec["jenis"]), suggested, ts, ts),
        )
        return "inserted"

    changes = {}
    if rec["status_berlaku"] != row["status_berlaku"] and rec.get("status_explicit", True):
        changes["status_berlaku"] = rec["status_berlaku"]
    if rec.get("url") and not row["url"]:
        changes["url"] = rec["url"]
    if rec.get("pdf_url") and not row["pdf_url"] and (not row["url"] or changes.get("url") or rec.get("url") == row["url"]):
        changes["pdf_url"] = rec["pdf_url"]
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
    stats = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0, "details": 0, "linked": 0}
    status, message = "ok", ""
    conn_obj = None
    try:
        conn_obj = connector or get_connector(source["kind"], source["base_url"],
                                              json.loads(source["config"] or "{}"))
        for rec in conn_obj.fetch(categories):
            stats["fetched"] += 1
            if categories and rec.get("category") is None:
                if classify(rec["judul"], rec["jenis"]) not in categories:
                    continue
            stats[upsert_regulation(conn, rec, source["id"])] += 1
        conn.commit()
        enrich(conn, conn_obj, categories, stats)
    except ConnectorError as exc:
        status, message = "error", str(exc)
    except Exception as exc:  # keep the app alive on unexpected markup / parsing errors
        status, message = "error", f"{type(exc).__name__}: {exc}"
    errors = conn_obj.errors if conn_obj else []
    if status == "ok":
        message = (f"{stats['fetched']} ditemukan, {stats['inserted']} baru, {stats['updated']} diperbarui, "
                   f"{stats['linked']} ditautkan ke halaman peraturan, {stats['details']} detail/PDF dibaca")
        if errors:
            # Nothing usable came back: report it as a failure with the first reason.
            useful = stats["fetched"] or stats["linked"] or stats["details"]
            status = "partial" if useful else "error"
            message = (message + f". {len(errors)} kendala, mis.: " if useful else "") + errors[0]
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


DETAIL_RECHECK = timedelta(days=30)


def _in_categories(categories, params):
    if not categories:
        return ""
    params.extend(categories)
    return f" AND category IN ({','.join('?' * len(categories))})"


def _apply_detail(conn, row, detail, url=None):
    """Store what a regulation's own page told us. Returns True if something changed."""
    changes = {"detail_checked_at": now()}
    if url and url != row["url"]:
        changes["url"] = url
    if detail.get("pdf_url") and detail["pdf_url"] != row["pdf_url"]:
        changes["pdf_url"] = detail["pdf_url"]
    if detail.get("status") and detail["status"] != row["status_berlaku"]:
        changes["status_berlaku"] = detail["status"]
    if detail.get("judul") and len(detail["judul"]) > len(row["judul"] or ""):
        changes["judul"] = detail["judul"]
    conn.execute(f"UPDATE regulations SET {', '.join(f'{k} = ?' for k in changes)}, updated_at = ? WHERE id = ?",
                 (*changes.values(), now(), row["id"]))
    return len(changes) > 1


def resolve_regulation(conn, connector, row):
    """Link one regulation to its own page (+PDF) on the connector's site.

    Raises ConnectorError on network failures. Returns True when the row was linked/updated.
    """
    url = row["url"] if connector.owns(row["url"]) else None
    if not url:
        if row["url"]:
            return False  # already linked to another site's page
        found = connector.lookup(row["jenis"], row["nomor"], row["tahun"])
        if not found:
            conn.execute("UPDATE regulations SET detail_checked_at = ? WHERE id = ?", (now(), row["id"]))
            return False
        url = found["url"]
        detail = {"pdf_url": found.get("pdf_url"),
                  "status": found["status_berlaku"] if found.get("status_explicit") else None}
        if not detail["pdf_url"]:
            detail.update({k: v for k, v in connector.fetch_detail(url).items() if v})
        return _apply_detail(conn, row, detail, url)
    return _apply_detail(conn, row, connector.fetch_detail(url))


def enrich(conn, connector, categories, stats):
    """Open regulations' own pages to fetch the PDF/status, and link entries that only had a citation."""
    cfg = connector.config
    detail_limit = int(cfg.get("detail_limit", 30))
    lookup_limit = int(cfg.get("lookup_limit", 20))
    stale = (datetime.now(timezone.utc) - DETAIL_RECHECK).isoformat(timespec="seconds")
    failures = 0

    params = [stale]
    rows = conn.execute(
        "SELECT * FROM regulations WHERE url IS NOT NULL AND pdf_url IS NULL "
        "AND (detail_checked_at IS NULL OR detail_checked_at < ?)" + _in_categories(categories, params) +
        " ORDER BY relevance = 'relevan' DESC, tahun DESC", params).fetchall()
    todo = [r for r in rows if connector.owns(r["url"])][:detail_limit]

    if lookup_limit and connector.supports_lookup:
        params = [stale]
        todo += conn.execute(
            "SELECT * FROM regulations WHERE url IS NULL "
            "AND (detail_checked_at IS NULL OR detail_checked_at < ?)" + _in_categories(categories, params) +
            " ORDER BY relevance = 'relevan' DESC, tahun DESC LIMIT ?", (*params, lookup_limit)).fetchall()

    for row in todo:
        had_url = bool(row["url"])
        try:
            if resolve_regulation(conn, connector, row):
                stats["details" if had_url else "linked"] += 1
            failures = 0
        except ConnectorError as exc:
            connector.errors.append(str(exc))
            failures += 1
            if failures >= 3:  # the site is likely blocking us; stop hammering it
                break
        conn.commit()


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
