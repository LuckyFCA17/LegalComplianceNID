"""Regulation categories and their keywords, stored in the database so admins can edit them."""
import json
import re

from .connectors.base import DEFAULT_KEYWORDS
from .db import now
from .legal import CATEGORY_KEYWORDS, FALLBACK_CATEGORY

MAX_CATEGORIES = 20
MAX_KEYWORDS = 60
NAME_RE = re.compile(r"^[\w][\w &/().,-]{0,39}$", re.UNICODE)


class CategoryError(ValueError):
    pass


def ensure_defaults(conn):
    """Create the shipped categories the first time (or after an upgrade from a version without them)."""
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]:
        return
    ts = now()
    builtin = ["K3", "Lingkungan", "Ketenagakerjaan", FALLBACK_CATEGORY]
    for pos, name in enumerate(builtin):
        conn.execute(
            "INSERT INTO categories (name, search_keywords, title_keywords, position, builtin, created_at, updated_at) "
            "VALUES (?,?,?,?,1,?,?)",
            (name, json.dumps(DEFAULT_KEYWORDS.get(name, [])), json.dumps(CATEGORY_KEYWORDS.get(name, [])),
             pos, ts, ts))
    conn.commit()


def _row(r):
    return {"id": r["id"], "name": r["name"], "search_keywords": json.loads(r["search_keywords"] or "[]"),
            "title_keywords": json.loads(r["title_keywords"] or "[]"), "position": r["position"],
            "builtin": bool(r["builtin"]), "fallback": r["name"] == FALLBACK_CATEGORY}


def load(conn):
    """All categories in display order; the fallback category is always last."""
    rows = conn.execute("SELECT * FROM categories ORDER BY name = ? COLLATE NOCASE, position, id",
                        (FALLBACK_CATEGORY,)).fetchall()
    return [_row(r) for r in rows]


def names(conn):
    return [c["name"] for c in load(conn)]


def rules(conn):
    """[(name, title keywords)] for legal.classify, in priority order."""
    return [(c["name"], c["title_keywords"]) for c in load(conn) if not c["fallback"]]


def search_map(conn):
    """{name: search keywords} for the connectors."""
    return {c["name"]: c["search_keywords"] for c in load(conn)}


def parse_keywords(value):
    """Accept a list or text separated by commas/new lines; returns a clean, de-duplicated list."""
    if value is None:
        return []
    items = value if isinstance(value, list) else re.split(r"[,\n;]", str(value))
    out, seen = [], set()
    for item in items:
        kw = " ".join(str(item).split())
        if not kw:
            continue
        if len(kw) > 80:
            raise CategoryError(f"Kata kunci terlalu panjang (maks. 80 karakter): {kw[:30]}…")
        if kw.lower() not in seen:
            seen.add(kw.lower())
            out.append(kw)
    if len(out) > MAX_KEYWORDS:
        raise CategoryError(f"Maksimal {MAX_KEYWORDS} kata kunci per daftar")
    return out


def _clean_name(name):
    name = " ".join(str(name or "").split())
    if not NAME_RE.match(name):
        raise CategoryError("Nama kategori 1–40 karakter: huruf, angka, spasi dan & / ( ) . , -")
    return name


def create(conn, name, search_keywords=None, title_keywords=None):
    name = _clean_name(name)
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise CategoryError(f"Kategori “{name}” sudah ada")
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] >= MAX_CATEGORIES:
        raise CategoryError(f"Maksimal {MAX_CATEGORIES} kategori")
    search = parse_keywords(search_keywords)
    # A new category with only search terms still needs title terms to receive any regulation.
    title = parse_keywords(title_keywords) if title_keywords not in (None, "", []) else search
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM categories").fetchone()[0]
    ts = now()
    cur = conn.execute(
        "INSERT INTO categories (name, search_keywords, title_keywords, position, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)", (name, json.dumps(search), json.dumps(title), pos, ts, ts))
    conn.commit()
    return cur.lastrowid


def get(conn, cid):
    row = conn.execute("SELECT * FROM categories WHERE id = ?", (cid,)).fetchone()
    return _row(row) if row else None


def update(conn, cid, data):
    cat = get(conn, cid)
    if cat is None:
        raise LookupError("Kategori tidak ditemukan")
    changes = {}
    if "name" in data and data["name"] != cat["name"]:
        if cat["fallback"]:
            raise CategoryError(f"Kategori “{FALLBACK_CATEGORY}” tidak dapat diganti nama")
        name = _clean_name(data["name"])
        clash = conn.execute("SELECT id FROM categories WHERE name = ? AND id != ?", (name, cid)).fetchone()
        if clash:
            raise CategoryError(f"Kategori “{name}” sudah ada")
        changes["name"] = name
    if "search_keywords" in data:
        changes["search_keywords"] = json.dumps(parse_keywords(data["search_keywords"]))
    if "title_keywords" in data:
        if cat["fallback"] and parse_keywords(data["title_keywords"]):
            raise CategoryError(f"“{FALLBACK_CATEGORY}” menampung peraturan yang tidak cocok kategori lain; "
                                "kata kunci judul tidak dipakai")
        changes["title_keywords"] = json.dumps(parse_keywords(data["title_keywords"]))
    if "position" in data:
        changes["position"] = int(data["position"])
    if not changes:
        return cat
    changes["updated_at"] = now()
    conn.execute(f"UPDATE categories SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                 (*changes.values(), cid))
    if "name" in changes:  # regulations store the category by name
        conn.execute("UPDATE regulations SET category = ? WHERE category = ? COLLATE NOCASE",
                     (changes["name"], cat["name"]))
    conn.commit()
    return get(conn, cid)


def delete(conn, cid):
    """Remove a category; its regulations move to the fallback category (and become auto-classified)."""
    cat = get(conn, cid)
    if cat is None:
        raise LookupError("Kategori tidak ditemukan")
    if cat["fallback"]:
        raise CategoryError(f"Kategori “{FALLBACK_CATEGORY}” tidak dapat dihapus")
    moved = conn.execute("UPDATE regulations SET category = ?, category_locked = 0 WHERE category = ? COLLATE NOCASE",
                         (FALLBACK_CATEGORY, cat["name"])).rowcount
    conn.execute("DELETE FROM categories WHERE id = ?", (cid,))
    conn.commit()
    return moved


def reclassify(conn, dry_run=False):
    """Re-run the title keywords over every regulation whose category was not set by hand."""
    from .legal import classify
    rl = rules(conn)
    moves = []
    for r in conn.execute("SELECT id, judul, jenis, category FROM regulations WHERE category_locked = 0").fetchall():
        cat = classify(r["judul"], r["jenis"], rl)
        if cat != r["category"]:
            moves.append((r["id"], r["category"], cat))
    if not dry_run:
        ts = now()
        for rid, _old, new in moves:
            conn.execute("UPDATE regulations SET category = ?, updated_at = ? WHERE id = ?", (new, ts, rid))
        conn.commit()
    summary = {}
    for _rid, old, new in moves:
        key = f"{old} → {new}"
        summary[key] = summary.get(key, 0) + 1
    return {"moved": len(moves), "changes": summary}
