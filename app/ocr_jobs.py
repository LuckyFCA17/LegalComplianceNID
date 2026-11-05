"""Run OCR of a stored scanned PDF in a background thread and record its progress in the database.

Progress lives in the ocr_jobs table, so every computer sharing the database (portable mode) sees it,
and a second computer cannot start the same OCR while one is running.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from . import analysis, ocr
from .db import connect, now, whoami

STALE = timedelta(minutes=10)  # no progress for this long: the computer running it stopped


class OcrBusy(Exception):
    pass


def pdf_dir(db_path):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "pdf")


def save_pdf(db_path, regulation_id, data):
    """Keep the original PDF next to the database so OCR can run later (from any computer)."""
    folder = pdf_dir(db_path)
    os.makedirs(folder, exist_ok=True)
    name = f"{regulation_id}.pdf"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)
    return name


def job(conn, regulation_id):
    row = conn.execute("SELECT * FROM ocr_jobs WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["active"] = d["status"] in ("running", "cancelling") and not _stale(d)
    if d["status"] in ("running", "cancelling") and not d["active"]:
        d["status"], d["message"] = "error", "OCR terhenti (komputer yang menjalankannya ditutup). Jalankan ulang."
    return d


def _stale(d):
    return datetime.fromisoformat(d["updated_at"]) < datetime.now(timezone.utc) - STALE


def start(conn, db_path, regulation_id, user_name):
    """Queue OCR for the regulation's stored PDF; raises OcrBusy or ValueError."""
    st = ocr.status()
    if not st["available"]:
        raise ValueError(st["message"])
    text = conn.execute("SELECT * FROM regulation_texts WHERE regulation_id = ?", (regulation_id,)).fetchone()
    if text is None or not text["pdf_file"]:
        raise ValueError("PDF aslinya tidak tersimpan. Ambil ulang dari PDF resmi atau unggah PDF-nya lagi.")
    path = os.path.join(pdf_dir(db_path), text["pdf_file"])
    if not os.path.isfile(path):
        raise ValueError("File PDF tidak ditemukan di folder data. Unggah PDF-nya lagi.")
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
                     "started_at, updated_at, message) VALUES (?, 'running', 0, 0, ?, ?, ?, 'Menyiapkan…')",
                     (regulation_id, holder, ts, ts))
        conn.execute("COMMIT")
    except OcrBusy:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    t = threading.Thread(target=_run, args=(db_path, regulation_id, path), daemon=True,
                         name=f"ocr-{regulation_id}")
    t.start()
    return t


def cancel(conn, regulation_id):
    conn.execute("UPDATE ocr_jobs SET status = 'cancelling', updated_at = ? WHERE regulation_id = ? "
                 "AND status = 'running'", (now(), regulation_id))
    conn.commit()


def _run(db_path, regulation_id, pdf_path):
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
        todo = [i for i, t in enumerate(layers) if len(t.strip()) < analysis.EMPTY_PAGE_CHARS] or list(range(len(layers)))
        update(total_pages=len(todo), message=f"OCR {len(todo)} halaman…")
        results = ocr.ocr_pdf(data, todo, progress=lambda n, total: update(done_pages=n), cancelled=cancelled)
        if cancelled():
            update(status="cancelled", message=f"Dibatalkan setelah {len(results)} dari {len(todo)} halaman")
            return
        pages, low = [], []
        for i, layer in enumerate(layers):
            if i in results:
                text, conf = results[i]
                pages.append(ocr.fix_ocr_text(text))
                if conf is not None and conf < ocr.LOW_CONFIDENCE:
                    low.append(i + 1)
            else:
                pages.append(layer)
        text = analysis.clean_text("\n".join(pages))
        conn.execute("UPDATE regulation_texts SET text = ?, origin = 'ocr', scanned = 0, needs_ocr = 0, "
                     "ocr_pages = ?, ocr_low_pages = ?, edited = 0, fetched_at = ? WHERE regulation_id = ?",
                     (text, len(results), json.dumps(low), now(), regulation_id))
        conn.commit()
        update(status="done", message=f"OCR selesai: {len(results)} halaman"
                                      + (f"; periksa halaman {', '.join(map(str, low))} (keyakinan rendah)" if low else ""))
    except Exception as exc:  # report every failure to the user instead of dying silently
        try:
            update(status="error", message=f"OCR gagal: {exc}")
        except Exception:
            pass
    finally:
        conn.close()
