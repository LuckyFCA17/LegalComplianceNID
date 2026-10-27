"""JSON API and SPA entry point."""
import csv
import io
import json
from datetime import date
from urllib.parse import quote_plus, urlparse

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_from_directory

from .connectors.base import make_record
from .connectors.jdihn import parse_feed
from .db import get_db, now
from .legal import CATEGORIES, citation, search_score, search_tokens
from .connectors import get_connector
from .connectors.base import DEFAULT_KEYWORDS, ConnectorError
from .sync import apply_suggestions, resolve_regulation, run_sync, upsert_regulation

bp = Blueprint("api", __name__)

RELEVANCE = ["pending", "relevan", "tidak_relevan"]
OBL_STATUS = ["belum", "proses", "terpenuhi", "tidak_berlaku"]
REG_STATUS = ["Berlaku", "Diubah", "Dicabut"]
# Compliance status of a relevant regulation, derived from its obligations.
COMPLIANCE = ["terpenuhi", "proses", "belum", "tanpa_kewajiban", "tidak_berlaku"]
REG_SORTS = {
    "tahun_desc": lambda r: (-(r["tahun"] or 0),),
    "tahun_asc": lambda r: (r["tahun"] or 9999,),
    # Regulations without a compliance figure (not relevant / no obligations) go last either way.
    "pemenuhan_asc": lambda r: (r["compliance_pct"] is None, r["compliance_pct"] or 0),
    "pemenuhan_desc": lambda r: (r["compliance_pct"] is None, -(r["compliance_pct"] or 0)),
    "judul": lambda r: (r["judul"].lower(),),
}


def compliance_of(row):
    """(status, pct) of a regulation from its obligation counts; (None, None) when not relevant."""
    if row["relevance"] != "relevan":
        return None, None
    total, done = row["obl_total"] or 0, row["obl_done"] or 0
    applicable = total - (row["obl_na"] or 0)
    if total == 0:
        return "tanpa_kewajiban", None
    if applicable == 0:
        return "tidak_berlaku", None
    pct = round(100 * done / applicable, 1)
    if done == applicable:
        return "terpenuhi", pct
    if done or row["obl_proses"]:
        return "proses", pct
    return "belum", pct


def _categories_arg():
    raw = request.args.get("category", "")
    cats = [c for c in raw.split(",") if c in CATEGORIES]
    return cats


def _in_clause(column, values, params):
    params.extend(values)
    return f"{column} IN ({','.join('?' * len(values))})"


def _reg_dict(row, with_counts=None):
    d = dict(row)
    d["suggested"] = json.loads(d.get("suggested") or "[]")
    d["citation"] = citation(row)
    d["search_url"] = "https://peraturan.bpk.go.id/Search?keywords=" + quote_plus(
        f"{row['jenis']} nomor {row['nomor']} tahun {row['tahun']}")
    if with_counts:
        d.update(with_counts)
    return d


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "Body JSON tidak valid")
    return data


@bp.errorhandler(400)
@bp.errorhandler(404)
def _err(e):
    return jsonify(error=e.description), e.code


# ---------------------------------------------------------------- SPA
@bp.get("/")
def index():
    return send_from_directory(current_app.static_folder, "index.html")


@bp.get("/api/meta")
def meta():
    return jsonify(categories=CATEGORIES, relevance=RELEVANCE, obligation_status=OBL_STATUS,
                   regulation_status=REG_STATUS, search_keywords=DEFAULT_KEYWORDS)


# ---------------------------------------------------------------- sources & sync
@bp.get("/api/sources")
def list_sources():
    rows = get_db().execute("SELECT * FROM sources ORDER BY id").fetchall()
    return jsonify([{**dict(r), "config": json.loads(r["config"] or "{}")} for r in rows])


@bp.patch("/api/sources/<int:sid>")
def update_source(sid):
    db = get_db()
    if not db.execute("SELECT 1 FROM sources WHERE id = ?", (sid,)).fetchone():
        abort(404, "Sumber tidak ditemukan")
    data = _json_body()
    if "enabled" in data:
        db.execute("UPDATE sources SET enabled = ? WHERE id = ?", (1 if data["enabled"] else 0, sid))
    if "base_url" in data:
        db.execute("UPDATE sources SET base_url = ? WHERE id = ?", (data["base_url"] or None, sid))
    if "config" in data:
        if not isinstance(data["config"], dict):
            abort(400, "config harus berupa objek JSON")
        db.execute("UPDATE sources SET config = ? WHERE id = ?", (json.dumps(data["config"]), sid))
    db.commit()
    return list_sources()


@bp.post("/api/sources/<int:sid>/test")
def test_source(sid):
    """Fetch one result page (and the first regulation's page) and report what the parser sees."""
    import re

    from .connectors.html_search import parse_results

    src = get_db().execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    if src is None:
        abort(404, "Sumber tidak ditemukan")
    conn = get_connector(src["kind"], src["base_url"], json.loads(src["config"] or "{}"))
    if not hasattr(conn, "search_url"):
        abort(400, "Tes koneksi hanya untuk sumber situs JDIH (BPK/Kemnaker)")
    data = request.get_json(silent=True) or {}
    keyword = (data.get("keyword") or "keselamatan kerja").strip()
    url = conn.search_url(keyword, 1)
    out = {"url": url, "keyword": keyword, "ok": False}
    try:
        resp = conn.get(url)
    except ConnectorError as exc:
        out["error"] = str(exc)
        out["notes"] = conn.notes
        return jsonify(out)
    hrefs = re.findall(r'href=["\']([^"\']+)', resp.text)
    records = parse_results(resp.text, url, conn.link_pattern, conn.pdf_pattern)
    out.update(http_status=resp.status_code, bytes=len(resp.text), links=len(hrefs),
               matching_links=sum(1 for h in hrefs if re.search(conn.link_pattern, h)),
               found=len(records),
               samples=[{"citation": f"{r['jenis']} No. {r['nomor']} Tahun {r['tahun']}", "judul": r["judul"],
                         "status": r["status_berlaku"], "url": r["url"], "pdf_url": r["pdf_url"]}
                        for r in records[:5]])
    if records:
        try:
            out["detail"] = {"url": records[0]["url"], **conn.fetch_detail(records[0]["url"])}
        except ConnectorError as exc:
            out["detail"] = {"url": records[0]["url"], "error": str(exc)}
    out["ok"] = bool(records)
    out["notes"] = conn.notes
    return jsonify(out)


@bp.post("/api/sync")
def sync():
    db = get_db()
    data = request.get_json(silent=True) or {}
    cats = [c for c in data.get("categories") or [] if c in CATEGORIES] or None
    ids = data.get("source_ids")
    if ids:
        params = []
        rows = db.execute(f"SELECT * FROM sources WHERE {_in_clause('id', ids, params)}", params).fetchall()
    else:
        rows = db.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
    results = [run_sync(db, r, cats) for r in rows]
    return jsonify(results)


@bp.get("/api/sync/log")
def sync_log():
    rows = get_db().execute(
        "SELECT l.*, s.name AS source_name FROM sync_log l JOIN sources s ON s.id = l.source_id "
        "ORDER BY l.id DESC LIMIT 30").fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------- regulations
@bp.get("/api/regulations")
def list_regulations():
    db = get_db()
    where, params = ["1=1"], []
    cats = _categories_arg()
    if cats:
        where.append(_in_clause("r.category", cats, params))
    for arg, col, allowed in (("relevance", "r.relevance", RELEVANCE), ("status", "r.status_berlaku", REG_STATUS)):
        val = request.args.get(arg)
        if val in allowed:
            where.append(f"{col} = ?")
            params.append(val)
    compliance = request.args.get("compliance", "")
    if compliance in COMPLIANCE or compliance == "terlambat":
        where.append("r.relevance = 'relevan'")  # compliance is only tracked for relevant regulations
    # Free-text search ("PP 50", "No. 5 Tahun 2018", "5/2018", "limbah") is matched per token below.
    tokens = search_tokens(request.args.get("q", ""))
    rows = db.execute(
        f"""SELECT r.*, s.name AS source_name,
               COUNT(o.id) AS obl_total,
               SUM(o.status = 'terpenuhi') AS obl_done,
               SUM(o.status = 'tidak_berlaku') AS obl_na,
               SUM(o.status = 'proses') AS obl_proses,
               SUM(o.due_date IS NOT NULL AND o.due_date != '' AND o.due_date < ?
                   AND o.status IN ('belum', 'proses')) AS obl_overdue
            FROM regulations r
            LEFT JOIN sources s ON s.id = r.source_id
            LEFT JOIN obligations o ON o.regulation_id = r.id
            WHERE {' AND '.join(where)}
            GROUP BY r.id
            ORDER BY CASE r.relevance WHEN 'relevan' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                     r.category, r.tahun DESC, r.jenis""",
        [date.today().isoformat(), *params]).fetchall()
    out, scores = [], {}
    for r in rows:
        if tokens:
            score = search_score(r, tokens)
            if score is None:
                continue
            scores[r["id"]] = score
        status, pct = compliance_of(r)
        d = _reg_dict(r, {"compliance_status": status, "compliance_pct": pct, "obl_overdue": r["obl_overdue"] or 0})
        if compliance == "terlambat" and not d["obl_overdue"]:
            continue
        if compliance in COMPLIANCE and status != compliance:
            continue
        out.append(d)
    sort = REG_SORTS.get(request.args.get("sort", ""))
    if sort:
        out.sort(key=sort)  # stable: ties keep the default relevance/category order
    elif scores:
        out.sort(key=lambda d: -scores[d["id"]])  # exact number/year matches first
    return jsonify(out)


def _get_reg(rid):
    row = get_db().execute("SELECT r.*, s.name AS source_name FROM regulations r "
                           "LEFT JOIN sources s ON s.id = r.source_id WHERE r.id = ?", (rid,)).fetchone()
    if row is None:
        abort(404, "Regulasi tidak ditemukan")
    return row


@bp.get("/api/regulations/<int:rid>")
def get_regulation(rid):
    row = _get_reg(rid)
    obls = get_db().execute("SELECT * FROM obligations WHERE regulation_id = ? ORDER BY id", (rid,)).fetchall()
    return jsonify({**_reg_dict(row), "obligations": [dict(o) for o in obls]})


def _set_relevance(db, rid, relevance, note=None):
    if relevance not in RELEVANCE:
        abort(400, "Nilai relevansi tidak valid")
    db.execute("UPDATE regulations SET relevance = ?, relevance_note = COALESCE(?, relevance_note), "
               "updated_at = ? WHERE id = ?", (relevance, note, now(), rid))
    if relevance == "relevan":
        apply_suggestions(db, rid)


@bp.patch("/api/regulations/<int:rid>")
def update_regulation(rid):
    db = get_db()
    _get_reg(rid)
    data = _json_body()
    if "relevance" in data:
        _set_relevance(db, rid, data["relevance"], data.get("relevance_note"))
    elif "relevance_note" in data:
        db.execute("UPDATE regulations SET relevance_note = ?, updated_at = ? WHERE id = ?",
                   (data["relevance_note"], now(), rid))
    if "category" in data:
        if data["category"] not in CATEGORIES:
            abort(400, "Kategori tidak valid")
        db.execute("UPDATE regulations SET category = ?, category_locked = 1, updated_at = ? WHERE id = ?",
                   (data["category"], now(), rid))
    for field in ("url", "pdf_url"):
        if field in data:
            val = (data[field] or "").strip() or None
            if val and urlparse(val).scheme not in ("http", "https"):
                abort(400, "Tautan harus diawali http:// atau https://")
            db.execute(f"UPDATE regulations SET {field} = ?, updated_at = ? WHERE id = ?", (val, now(), rid))
    if "status_berlaku" in data:
        if data["status_berlaku"] not in REG_STATUS:
            abort(400, "Status berlaku tidak valid")
        db.execute("UPDATE regulations SET status_berlaku = ?, updated_at = ? WHERE id = ?",
                   (data["status_berlaku"], now(), rid))
    db.commit()
    return get_regulation(rid)


@bp.post("/api/regulations/<int:rid>/detail")
def fetch_regulation_detail(rid):
    """Open the regulation's own JDIH page (finding it first if needed) to get its PDF and status."""
    db = get_db()
    row = _get_reg(rid)
    sources = db.execute("SELECT * FROM sources WHERE kind IN ('bpk', 'kemnaker', 'html') "
                         "ORDER BY enabled DESC, id").fetchall()
    errors, changed = [], False
    for src in sources:
        conn = get_connector(src["kind"], src["base_url"], json.loads(src["config"] or "{}"))
        if row["url"] and not conn.owns(row["url"]):
            continue
        if not row["url"] and not conn.supports_lookup:
            continue
        try:
            changed = resolve_regulation(db, conn, row)
            db.commit()
            row = _get_reg(rid)
            if row["pdf_url"]:
                break
        except ConnectorError as exc:
            errors.append(str(exc))
    out = get_regulation(rid).get_json()
    if row["pdf_url"]:
        out["message"] = "Halaman peraturan dan PDF ditemukan"
    elif errors:
        out["message"] = "Gagal menghubungi JDIH: " + errors[0]
    elif row["url"]:
        out["message"] = "Halaman peraturan ditemukan, tetapi tautan PDF tidak terdeteksi"
    else:
        out["message"] = "Peraturan tidak ditemukan di JDIH. Isi tautan secara manual."
    out["changed"] = changed
    return jsonify(out)


@bp.post("/api/regulations/bulk")
def bulk_update():
    db = get_db()
    data = _json_body()
    ids = [int(i) for i in data.get("ids") or []]
    if not ids:
        abort(400, "ids kosong")
    for rid in ids:
        if "relevance" in data:
            _set_relevance(db, rid, data["relevance"])
        if data.get("category") in CATEGORIES:
            db.execute("UPDATE regulations SET category = ?, category_locked = 1, updated_at = ? WHERE id = ?",
                       (data["category"], now(), rid))
    db.commit()
    return jsonify(updated=len(ids))


@bp.post("/api/regulations")
def create_regulation():
    db = get_db()
    data = _json_body()
    rec = make_record(data.get("jenis"), data.get("nomor"), data.get("tahun"), data.get("judul"),
                      status=data.get("status_berlaku"), url=data.get("url"))
    if not rec:
        abort(400, "jenis, nomor dan judul wajib diisi")
    if data.get("category") in CATEGORIES:
        rec["category"] = data["category"]
    manual = db.execute("SELECT id FROM sources WHERE code = 'manual'").fetchone()
    if manual is None:
        db.execute("INSERT INTO sources (code, name, kind, enabled) VALUES ('manual', 'Input Manual', 'manual', 0)")
        manual = db.execute("SELECT id FROM sources WHERE code = 'manual'").fetchone()
    result = upsert_regulation(db, rec, manual["id"])
    db.commit()
    return jsonify(result=result), 201 if result == "inserted" else 200


@bp.post("/api/import")
def import_file():
    """Import regulations from an uploaded CSV (jenis,nomor,tahun,judul,status,url,category) or JSON feed."""
    db = get_db()
    f = request.files.get("file")
    if not f:
        abort(400, "File tidak ditemukan")
    text = f.read().decode("utf-8-sig", errors="replace")
    if f.filename.lower().endswith(".json"):
        try:
            records = parse_feed(json.loads(text))
        except ValueError as exc:
            abort(400, f"JSON tidak valid: {exc}")
    else:
        records = []
        for row in csv.DictReader(io.StringIO(text)):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            rec = make_record(row.get("jenis"), row.get("nomor"), row.get("tahun"), row.get("judul"),
                              status=row.get("status") or row.get("status_berlaku"), url=row.get("url"))
            if rec:
                if row.get("category") in CATEGORIES:
                    rec["category"] = row["category"]
                records.append(rec)
    src = db.execute("SELECT id FROM sources WHERE code = 'import'").fetchone()
    if src is None:
        db.execute("INSERT INTO sources (code, name, kind, enabled) VALUES ('import', 'Impor File', 'import', 0)")
        src = db.execute("SELECT id FROM sources WHERE code = 'import'").fetchone()
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    for rec in records:
        stats[upsert_regulation(db, rec, src["id"])] += 1
    db.commit()
    return jsonify(fetched=len(records), **stats)


# ---------------------------------------------------------------- obligations
def _obl_payload(data, partial):
    out = {}
    for k in ("pasal", "description", "pic", "due_date", "evidence", "notes", "status"):
        if k in data:
            out[k] = (data[k] or "").strip() if isinstance(data[k], str) else data[k]
    if "status" in out and out["status"] not in OBL_STATUS:
        abort(400, "Status pemenuhan tidak valid")
    if out.get("due_date"):
        try:
            date.fromisoformat(out["due_date"])
        except ValueError:
            abort(400, "Format due_date harus YYYY-MM-DD")
    if not partial and not out.get("description"):
        abort(400, "Deskripsi kewajiban wajib diisi")
    return out


@bp.post("/api/regulations/<int:rid>/obligations")
def create_obligation(rid):
    db = get_db()
    _get_reg(rid)
    data = _obl_payload(_json_body(), partial=False)
    data.setdefault("status", "belum")
    ts = now()
    cols = ["regulation_id", *data.keys(), "created_at", "updated_at"]
    cur = db.execute(f"INSERT INTO obligations ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     (rid, *data.values(), ts, ts))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM obligations WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


@bp.patch("/api/obligations/<int:oid>")
def update_obligation(oid):
    db = get_db()
    if not db.execute("SELECT 1 FROM obligations WHERE id = ?", (oid,)).fetchone():
        abort(404, "Kewajiban tidak ditemukan")
    data = _obl_payload(_json_body(), partial=True)
    if data:
        data["updated_at"] = now()
        db.execute(f"UPDATE obligations SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                   (*data.values(), oid))
        db.commit()
    return jsonify(dict(db.execute("SELECT * FROM obligations WHERE id = ?", (oid,)).fetchone()))


@bp.delete("/api/obligations/<int:oid>")
def delete_obligation(oid):
    db = get_db()
    db.execute("DELETE FROM obligations WHERE id = ?", (oid,))
    db.commit()
    return "", 204


def _obligation_rows(cats):
    where, params = ["r.relevance = 'relevan'"], []
    if cats:
        where.append(_in_clause("r.category", cats, params))
    return get_db().execute(
        f"""SELECT o.*, r.jenis, r.nomor, r.tahun, r.judul, r.category, r.status_berlaku
            FROM obligations o JOIN regulations r ON r.id = o.regulation_id
            WHERE {' AND '.join(where)} ORDER BY r.category, r.id, o.id""", params).fetchall()


@bp.get("/api/obligations")
def list_obligations():
    rows = _obligation_rows(_categories_arg())
    status = request.args.get("status")
    out = []
    for r in rows:
        if status in OBL_STATUS and r["status"] != status:
            continue
        out.append({**dict(r), "citation": citation(r)})
    return jsonify(out)


# ---------------------------------------------------------------- dashboard & export
def _pct(done, applicable):
    return round(100 * done / applicable, 1) if applicable else None


@bp.get("/api/dashboard")
def dashboard():
    db = get_db()
    cats = _categories_arg() or CATEGORIES
    today = date.today().isoformat()

    params = []
    reg_rows = db.execute(
        f"SELECT category, relevance, status_berlaku, COUNT(*) n FROM regulations "
        f"WHERE {_in_clause('category', cats, params)} GROUP BY 1,2,3", params).fetchall()
    obls = _obligation_rows(cats)

    per_cat = {c: {"category": c, "regulations": 0, "relevan": 0, "pending": 0, "tidak_relevan": 0,
                   "obligations": {s: 0 for s in OBL_STATUS}} for c in cats}
    for r in reg_rows:
        pc = per_cat[r["category"]]
        pc["regulations"] += r["n"]
        pc[r["relevance"]] += r["n"]
    overdue = []
    for o in obls:
        per_cat[o["category"]]["obligations"][o["status"]] += 1
        if o["due_date"] and o["due_date"] < today and o["status"] in ("belum", "proses"):
            overdue.append({**dict(o), "citation": citation(o)})
    for pc in per_cat.values():
        ob = pc["obligations"]
        pc["obligation_total"] = sum(ob.values())
        pc["compliance_pct"] = _pct(ob["terpenuhi"], pc["obligation_total"] - ob["tidak_berlaku"])

    totals = {s: sum(pc["obligations"][s] for pc in per_cat.values()) for s in OBL_STATUS}
    applicable = sum(totals.values()) - totals["tidak_berlaku"]

    params = []
    review = db.execute(
        f"SELECT * FROM regulations WHERE relevance = 'relevan' AND status_berlaku IN ('Dicabut','Diubah') "
        f"AND {_in_clause('category', cats, params)} ORDER BY tahun DESC", params).fetchall()
    params = []
    no_obl = db.execute(
        f"SELECT r.* FROM regulations r WHERE r.relevance = 'relevan' AND {_in_clause('r.category', cats, params)} "
        f"AND NOT EXISTS (SELECT 1 FROM obligations o WHERE o.regulation_id = r.id)", params).fetchall()

    return jsonify(
        categories=cats,
        summary={
            "regulations": sum(pc["regulations"] for pc in per_cat.values()),
            "relevan": sum(pc["relevan"] for pc in per_cat.values()),
            "pending": sum(pc["pending"] for pc in per_cat.values()),
            "tidak_relevan": sum(pc["tidak_relevan"] for pc in per_cat.values()),
            "obligations": totals,
            "obligation_total": sum(totals.values()),
            "compliance_pct": _pct(totals["terpenuhi"], applicable),
            "overdue": len(overdue),
        },
        per_category=list(per_cat.values()),
        overdue=sorted(overdue, key=lambda o: o["due_date"])[:20],
        review_needed=[_reg_dict(r) for r in review],
        without_obligations=[_reg_dict(r) for r in no_obl],
        sources=[dict(r) for r in db.execute(
            "SELECT name, last_sync, last_status, enabled FROM sources ORDER BY id").fetchall()],
    )


@bp.get("/api/export.csv")
def export_csv():
    rows = _obligation_rows(_categories_arg())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Kategori", "Regulasi", "Tentang", "Status Regulasi", "Pasal", "Kewajiban", "PIC",
                "Tenggat", "Status Pemenuhan", "Bukti", "Catatan"])
    for r in rows:
        w.writerow([r["category"], citation(r), r["judul"], r["status_berlaku"], r["pasal"], r["description"],
                    r["pic"], r["due_date"], r["status"], r["evidence"], r["notes"]])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=register-kepatuhan.csv"})
