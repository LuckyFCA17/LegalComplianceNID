"""Portable launcher: double-click to run Legal Compliance on this computer.

The program can live in a shared folder (e.g. \\\\server\\aplikasi\\LegalCompliance). Each computer
that opens it runs its own small web server on 127.0.0.1 and opens the browser; all of them use
the same database in the "data" folder next to the program (or the folder named in
data-location.txt). The app then switches SQLite to settings that are safe on a network share,
takes a database-wide lock while syncing and backs the database up before every sync.

Options:  --check   start, self-test and exit (used by the build pipeline)
          --no-browser
"""
import json
import os
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

APP_NAME = "LegalComplianceNID"
PREFERRED_PORTS = range(5050, 5060)


def base_dir():
    if getattr(sys, "frozen", False):  # PyInstaller build
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """data/ next to the program, or the folder written in data-location.txt, or LCN_DATA_DIR."""
    if os.environ.get("LCN_DATA_DIR"):
        return os.environ["LCN_DATA_DIR"]
    override = os.path.join(base_dir(), "data-location.txt")
    if os.path.exists(override):
        with open(override, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return os.path.join(base_dir(), "data")


def state_file():
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(root, APP_NAME, "running.json")


def pause(msg="Tekan Enter untuk menutup jendela ini..."):
    if sys.stdin and sys.stdin.isatty():
        try:
            input(msg)
        except EOFError:
            pass


def already_running(data):
    """If this computer already runs the app for the same data folder, return its URL."""
    try:
        with open(state_file(), encoding="utf-8") as f:
            st = json.load(f)
        if os.path.normcase(st.get("data", "")) != os.path.normcase(data):
            return None
        url = f"http://127.0.0.1:{st['port']}"
        with urllib.request.urlopen(url + "/healthz", timeout=2) as resp:
            if json.load(resp).get("app") == APP_NAME:
                return url
    except Exception:
        return None
    return None


def free_port():
    for port in list(PREFERRED_PORTS) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Tidak ada port lokal yang kosong")


def check_writable(folder):
    os.makedirs(folder, exist_ok=True)
    probe = os.path.join(folder, f".tulis-{socket.gethostname()}-{os.getpid()}.tmp")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)


def check_integrity(db_path):
    """Refuse to start on a damaged database instead of making it worse."""
    if not os.path.exists(db_path):
        return True
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        rows = [r[0] for r in conn.execute("PRAGMA quick_check(5)")]
    except sqlite3.DatabaseError as exc:  # header or pages unreadable
        rows = [str(exc)]
    finally:
        conn.close()
    if rows == ["ok"]:
        return True
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    backups = sorted(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else []
    print("\n!!! DATABASE RUSAK — aplikasi tidak dijalankan agar kerusakan tidak bertambah.")
    print("    Hasil pemeriksaan:", "; ".join(rows))
    print("    Cara memulihkan: tutup aplikasi di SEMUA komputer, lalu salin backup terbaru dari")
    print(f"    {backup_dir}")
    print(f"    menjadi {db_path}")
    if backups:
        print("    Backup terbaru:", backups[-1])
    return False


def _check_ocr():
    """OCR a rendered test line. Required when LCN_REQUIRE_OCR=1 (the build pipeline), optional otherwise."""
    import tempfile

    from PIL import Image, ImageDraw, ImageFont

    import pypdfium2  # noqa: F401  (bundled to render scanned PDF pages)
    from app import ocr

    st = ocr.status(refresh=True)
    required = os.environ.get("LCN_REQUIRE_OCR") == "1"
    if not st["available"]:
        print(" OCR       :", "TIDAK TERSEDIA —", st["message"])
        return not required
    img = Image.new("L", (1800, 220), 255)
    ImageDraw.Draw(img).text((40, 60), "Setiap perusahaan wajib menerapkan SMK3", fill=0,
                             font=ImageFont.load_default(size=64))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "uji.png")
        img.save(path)
        text, conf = ocr.ocr_image(st["path"], st["lang"], path)
    good = "wajib" in text.lower()
    print(f" OCR       : {'OK' if good else 'GAGAL'} ({st['lang']}, keyakinan {conf or 0:.0f}) — {st['path']}")
    return good or not required


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    check_only = "--check" in argv
    data = os.path.abspath(data_dir())
    db_path = os.path.join(data, "compliance.db")

    print("=" * 64)
    print(" Legal Compliance NID — versi portable")
    print("=" * 64)
    print(f" Folder data : {data}")

    if not check_only:
        url = already_running(data)
        if url:
            print(f" Aplikasi sudah berjalan di komputer ini: {url}")
            webbrowser.open(url)
            return 0

    try:
        check_writable(data)
    except OSError as exc:
        print(f"\n!!! Folder data tidak bisa ditulis: {exc}")
        print("    Pastikan Anda punya izin baca-tulis ke folder bersama ini.")
        pause()
        return 2
    if not check_integrity(db_path):
        pause()
        return 3

    os.environ["LCN_PORTABLE"] = "1"
    os.environ["LCN_DATABASE"] = db_path
    from app import create_app  # imported late so the environment above is in effect

    app = create_app()

    if check_only:
        client = app.test_client()
        ok = (client.get("/healthz").get_json() or {}).get("app") == APP_NAME
        ok = ok and b"Legal Compliance" in client.get("/login").data
        ok = ok and client.get("/static/app.js").status_code == 200
        from pypdf import PdfReader  # noqa: F401  (bundled for the legal analysis)
        from app.analysis import analyze
        ok = ok and analyze("Pasal 5\n(1) Setiap perusahaan wajib menerapkan SMK3.")["candidates"] != []
        ok = ok and _check_ocr()
        print(" Self-test:", "OK" if ok else "GAGAL")
        return 0 if ok else 1

    from waitress import serve

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    os.makedirs(os.path.dirname(state_file()), exist_ok=True)
    with open(state_file(), "w", encoding="utf-8") as f:
        json.dump({"port": port, "data": data, "pid": os.getpid(), "started": time.time()}, f)

    print(f" Alamat      : {url}")
    print(" Mode        : portable (database bersama, aman untuk folder jaringan)")
    print("-" * 64)
    print(" Browser akan terbuka otomatis. Biarkan jendela ini tetap terbuka.")
    print(" Untuk keluar: tutup jendela ini (atau tekan Ctrl+C).")
    print("-" * 64)
    if "--no-browser" not in argv:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    try:
        serve(app, host="127.0.0.1", port=port, threads=6, _quiet=True)
    finally:
        try:
            os.remove(state_file())
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        print("\n!!! Aplikasi berhenti karena kesalahan di atas.")
        pause()
        sys.exit(1)
