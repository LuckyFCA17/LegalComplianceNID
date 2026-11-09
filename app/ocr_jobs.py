"""Run OCR of a stored PDF in a background thread and record its progress in the database.

Progress lives in the ocr_jobs table, so every computer sharing the database (portable mode) sees it,
and a second computer cannot start the same OCR while one is running.

Modes: "scan" (pages without a text layer), "all" (every page, ignoring the PDF's own text layer —
for PDFs whose embedded OCR is poor) and "pages" (a list such as "1,3-5"). When the regulation already
has usable text, the result waits for review ("review") so the person can compare and choose; the text
it replaces is kept as a version that can be restored.
"""
import json
import os
import re
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import analysis, ocr
from .db import connect, now, whoami
from .ocr_correct import build_lexicon, correct, correct_words, text_quality

STALE = timedelta(minutes=10)  # no progress for this long: the computer running it stopped
MODES = ("scan", "all", "pages")
POOR_QUALITY = 70  # text_quality below this: suggest OCR again


class OcrBusy(Exception):
    pass


def pdf_dir(db_path):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "pdf")


def save_pdf(db_path, regulation_id, data):
    """Keep the original PDF next to the database so OCR can run (again) later, from any computer."""
    folder = pdf_dir(db_path)
    os.makedirs(folder, exist_ok=True)
    name = f"{regulation_id}.pdf"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)
    return name


def trusted_lexicon(conn):
    """Lexicon from built-in words plus texts that are known to be clean (good text layer or hand-edited)."""
    rows = conn.execute("SELECT text FROM regulation_texts WHERE edited = 1 OR "
                        "(origin IN ('pdf_url', 'upload', 'paste') AND COALESCE(text_quality, 0) >= 85) "
                        "ORDER BY fetched_at DESC LIMIT 300").fetchall()
    return build_lexicon(r["text"] for r in rows)


def parse_pages(spec, total):
    """'1,3-5' -> [0, 2, 3, 4] (indexes). Raises ValueError for anything outside 1..total."""
    out = set()
    for part in re.split(r"[,\s;]+", (spec or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"Halaman tidak dikenali: “{part}” (contoh: 1,3-5)")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b > total or a > b:
            raise ValueError(f"Halaman {part} di luar 1–{total}")
        out.update(range(a - 1, b))
    if not out:
        raise ValueError("Tulis nomor halaman, mis. 1,3-5")
    return sorted(out)


def job(conn, regulation_id):
    row = conn.execute("SELECT * FROM ocr_jobs WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d.pop("result_text", None)
    d["result"] = json.loads(d.pop("result_meta") or "null")
    d["active"] = d["status"] in ("running", "cancelling") and not _stale(d)
    if d["status"] in ("running", "cancelling") and not d["active"]:
        d["status"], d["message"] = "error", "OCR terhenti (komputer yang menjalankannya ditutup). Jalankan ulang."
    return d


def _stale(d):
    return datetime.fromisoformat(d["updated_at"]) < datetime.now(timezone.utc) - STALE


def start(conn, db_path, regulation_id, user_name, mode="scan", pages=None, quality="standar"):
    """Queue OCR of the regulation's stored PDF; raises OcrBusy or ValueError."""
    st = ocr.status()
    if not st["available"]:
        raise ValueError(st["message"])
    if mode not in MODES:
        raise ValueError("Mode OCR tidak dikenal")
    if quality not in ocr.QUALITIES:
        raise ValueError("Ketelitian OCR tidak dikenal")
    text = conn.execute("SELECT * FROM regulation_texts WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if text is None or not text["pdf_file"]:
        raise ValueError("PDF aslinya tidak tersimpan. Ambil ulang dari PDF resmi atau unggah PDF-nya lagi.")
    path = os.path.join(pdf_dir(db_path), text["pdf_file"])
    if not os.path.isfile(path):
        raise ValueError("File PDF tidak ditemukan di folder data. Unggah PDF-nya lagi.")
    if mode == "pages":
        if not text["pages"]:
            with open(path, "rb") as f:
                total = len(analysis.page_texts(f.read()))
        else:
            total = text["pages"]
        parse_pages(pages, total)
    holder = f"{user_name} di {whoami()}"
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")  # one OCR per regulation, across computers
    try:
        cur = job(conn, regulation_id)
        if cur and cur["active"]:
            conn.execute("ROLLBACK")
            raise OcrBusy(f"OCR peraturan ini sedang dijalankan oleh {cur['holder']}")
        ts = now()
        conn.execute("INSERT OR REPLACE INTO ocr_jobs (regulation_id, status, done_pages, total_pages, holder, "
                     "started_at, updated_at, message, mode, quality, pages_spec, result_text, result_meta) "
                     "VALUES (?, 'running', 0, 0, ?, ?, ?, 'Menyiapkan…', ?, ?, ?, NULL, NULL)",
                     (regulation_id, holder, ts, ts, mode, quality, pages))
        conn.execute("COMMIT")
    except OcrBusy:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    t = threading.Thread(target=_run, args=(db_path, regulation_id, path, mode, pages, quality, user_name),
                         daemon=True, name=f"ocr-{regulation_id}")
    t.start()
    return t


def cancel(conn, regulation_id):
    conn.execute("UPDATE ocr_jobs SET status = 'cancelling', updated_at = ? WHERE regulation_id = ? "
                 "AND status = 'running'", (now(), regulation_id))
    conn.commit()


def save_version(conn, regulation_id, row, user_name, reason):
    """Keep the current text before it is replaced."""
    meta = {k: row[k] for k in ("text_quality", "ocr_conf", "ocr_mode", "edited", "ocr_pages", "pages")
            if k in row.keys()}
    conn.execute("INSERT INTO regulation_text_versions (regulation_id, origin, text, meta, saved_at, saved_by, reason) "
                 "VALUES (?,?,?,?,?,?,?)", (regulation_id, row["origin"], row["text"], json.dumps(meta), now(),
                                            user_name, reason))


def apply_result(conn, regulation_id, text, meta, user_name):
    """Make an OCR result the regulation's text; the previous text is kept as a version."""
    row = conn.execute("SELECT * FROM regulation_texts WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if row is not None and row["text"].strip():
        save_version(conn, regulation_id, row, user_name, f"diganti hasil OCR ({meta.get('quality', '')})")
    conn.execute("UPDATE regulation_texts SET text = ?, origin = 'ocr', scanned = 0, needs_ocr = ?, ocr_pages = ?, "
                 "ocr_low_pages = ?, edited = 0, fetched_at = ?, fetched_by = ?, text_quality = ?, ocr_conf = ?, "
                 "ocr_mode = ? WHERE regulation_id = ?",
                 (text, meta.get("pages_left", 0), meta.get("pages_ocr", 0), json.dumps(meta.get("low_pages", [])),
                  now(), user_name, meta.get("text_quality"), meta.get("mean_conf"),
                  f"{meta.get('mode')}/{meta.get('quality')}", regulation_id))


def _needs_review(row, mode):
    """Ask the person before replacing text they could lose: hand-edited text, or pages that already had text
    (modes "all"/"pages"). Filling only image pages ("scan") keeps every existing page, so it applies directly."""
    if row is None:
        return False
    if row["edited"]:
        return True
    return mode != "scan" and len(row["text"].strip()) >= 200


def _run(db_path, regulation_id, pdf_path, mode, pages_spec, quality, user_name):
    conn = connect(db_path)

    def update(**fields):
        fields["updated_at"] = now()
        conn.execute(f"UPDATE ocr_jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE regulation_id = ?",
                     (*fields.values(), regulation_id))
        conn.commit()

    def cancelled():
        row = conn.execute("SELECT status FROM ocr_jobs WHERE regulation_id = ?", (regulation_id,)).fetchone()
        return row is None or row["status"] == "cancelling"

    try:
        with open(pdf_path, "rb") as f:
            data = f.read()
        layers = analysis.page_texts(data)
        empty = [i for i, t in enumerate(layers) if len(t.strip()) < analysis.EMPTY_PAGE_CHARS]
        if mode == "all":
            todo = list(range(len(layers)))
        elif mode == "pages":
            todo = parse_pages(pages_spec, len(layers))
        else:
            todo = empty
        if not todo:
            update(status="error", message="Tidak ada halaman scan di PDF ini. Pilih “Semua halaman” untuk "
                                           "membaca ulang halaman yang sudah punya teks.")
            return
        update(total_pages=len(todo), message=f"OCR {len(todo)} halaman ({quality})…")
        results = ocr.ocr_pdf(data, todo, progress=lambda n, total: update(done_pages=n), cancelled=cancelled,
                              quality=quality)
        if cancelled():
            update(status="cancelled", message=f"Dibatalkan setelah {len(results)} dari {len(todo)} halaman")
            return
        lexicon = trusted_lexicon(conn)
        pages, low, confs, variants, changes = [], [], [], Counter(), []
        for i, layer in enumerate(layers):
            if i in results:
                text, conf, variant, unsure = results[i]
                # only words the OCR engine itself was unsure about may be corrected
                text, page_changes = correct_words(text, lexicon, only=unsure)
                changes += page_changes
                pages.append(text)
                variants[variant] += 1
                if conf is not None:
                    confs.append(conf)
                    if conf < ocr.LOW_CONFIDENCE:
                        low.append(i + 1)
            else:
                pages.append(layer)
        # Structure first, on the raw OCR lines: clean_text would glue a noisy heading ("Pasal 3 : AN")
        # to the line before it, and then it could no longer be recognised.
        text = analysis.clean_text(correct("\n".join(pages), lexicon, only=set())[0])
        found = analysis.analyze(text)
        meta = {"mode": mode, "quality": quality, "pages_ocr": len(results), "low_pages": low,
                "pages_left": len([i for i in empty if i not in results]),
                "mean_conf": round(sum(confs) / len(confs), 1) if confs else None,
                "variants": dict(variants), "corrections": len(changes),
                "correction_examples": [f"{a} → {b}" for a, b in changes[:8]],
                "text_quality": text_quality(text, lexicon), "chars": len(text),
                "articles": found["articles"], "candidates": len(found["candidates"])}
        row = conn.execute("SELECT * FROM regulation_texts WHERE regulation_id = ?", (regulation_id,)).fetchone()
        summary = (f"{len(results)} halaman, keyakinan rata-rata {meta['mean_conf'] or 0:.0f}, "
                   f"{len(changes)} koreksi otomatis")
        if _needs_review(row, mode):
            update(status="review", result_text=text, result_meta=json.dumps(meta),
                   message=f"OCR selesai ({summary}). Bandingkan dengan teks lama lalu pilih yang dipakai.")
        else:
            apply_result(conn, regulation_id, text, meta, user_name)
            conn.commit()
            update(status="done", result_meta=json.dumps(meta), message=f"OCR selesai: {summary}"
                   + (f"; periksa halaman {', '.join(map(str, low))} (keyakinan rendah)" if low else ""))
    except Exception as exc:  # report every failure to the user instead of dying silently
        try:
            update(status="error", message=f"OCR gagal: {exc}")
        except Exception:
            pass
    finally:
        conn.close()


def accept(conn, regulation_id, user_name):
    row = conn.execute("SELECT * FROM ocr_jobs WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if row is None or row["status"] != "review" or not row["result_text"]:
        raise ValueError("Tidak ada hasil OCR yang menunggu keputusan")
    apply_result(conn, regulation_id, row["result_text"], json.loads(row["result_meta"] or "{}"), user_name)
    conn.execute("UPDATE ocr_jobs SET status = 'done', result_text = NULL, updated_at = ?, "
                 "message = 'Hasil OCR baru dipakai; teks lama disimpan sebagai versi sebelumnya.' "
                 "WHERE regulation_id = ?", (now(), regulation_id))
    conn.commit()


def discard(conn, regulation_id):
    conn.execute("UPDATE ocr_jobs SET status = 'discarded', result_text = NULL, updated_at = ?, "
                 "message = 'Hasil OCR baru dibuang; teks lama tetap dipakai.' "
                 "WHERE regulation_id = ? AND status = 'review'", (now(), regulation_id))
    conn.commit()
