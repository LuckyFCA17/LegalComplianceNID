"""Login, roles and user management.

Roles:
  admin  — everything, incl. user management and source configuration
  editor — assess relevance, manage obligations, import, run sync
  viewer — read-only (dashboard, lists, export)
"""
import os
import re
import time
from collections import defaultdict, deque

from flask import (Blueprint, abort, current_app, g, jsonify, redirect, request, send_from_directory,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now

bp = Blueprint("auth", __name__)

ROLES = ["admin", "editor", "viewer"]
MIN_PASSWORD = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PUBLIC_PATHS = {"/login", "/healthz", "/api/auth/login", "/api/auth/setup", "/api/auth/status"}
# (method, path regex) that need admin; everything else that writes needs editor.
ADMIN_ONLY = [
    ("PATCH", re.compile(r"^/api/sources/")),
    ("*", re.compile(r"^/api/users")),
]
SELF_SERVICE = {"/api/auth/logout", "/api/auth/password"}

# Simple per-IP throttle against password guessing: max failures per window.
_FAILS = defaultdict(deque)
FAIL_LIMIT, FAIL_WINDOW = 10, 15 * 60


def _client_ip():
    return request.remote_addr or "?"


def _throttled(ip):
    q = _FAILS[ip]
    cutoff = time.time() - FAIL_WINDOW
    while q and q[0] < cutoff:
        q.popleft()
    return len(q) >= FAIL_LIMIT


def _user_dict(row):
    return {k: row[k] for k in ("id", "email", "name", "role", "active", "created_at", "last_login")}


def _validate_password(pw):
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        abort(400, f"Password minimal {MIN_PASSWORD} karakter")


def create_user(conn, email, name, password, role="viewer"):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        abort(400, "Email tidak valid")
    if role not in ROLES:
        abort(400, "Peran tidak valid")
    _validate_password(password)
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        abort(400, "Email sudah terdaftar")
    cur = conn.execute(
        "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        (email, (name or email.split("@")[0]).strip(), generate_password_hash(password), role, now()))
    conn.commit()
    return cur.lastrowid


def bootstrap_admin(conn):
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD when the users table is empty."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    email, pw = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not (email and pw):
        return False
    conn.execute(
        "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        (email.strip().lower(), "Administrator", generate_password_hash(pw), "admin", now()))
    conn.commit()
    return True


def _has_users():
    return bool(get_db().execute("SELECT 1 FROM users LIMIT 1").fetchone())


def _setup_allowed():
    # First-run setup through the browser is only for installs without ADMIN_* env vars;
    # deployments should always set them so nobody else can claim the first account.
    return not _has_users() and not current_app.config.get("REQUIRE_ENV_ADMIN")


@bp.before_app_request
def enforce_auth():
    path = request.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return None
    uid = session.get("uid")
    user = None
    if uid:
        user = get_db().execute("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        if user is None:
            session.clear()
    if user is None:
        if path.startswith("/api/"):
            return jsonify(error="Silakan login terlebih dahulu"), 401
        return redirect("/login")
    g.user = user
    if request.method in ("GET", "HEAD") and not path.startswith("/api/users"):
        return None
    if path in SELF_SERVICE:
        return None
    for method, rx in ADMIN_ONLY:
        if (method == "*" or method == request.method) and rx.search(path):
            if user["role"] != "admin":
                return jsonify(error="Hanya admin yang dapat melakukan ini"), 403
            return None
    if user["role"] not in ("admin", "editor"):
        return jsonify(error="Peran viewer hanya dapat melihat data"), 403
    return None


@bp.get("/healthz")
def healthz():
    get_db().execute("SELECT 1")
    return jsonify(ok=True)


@bp.get("/login")
def login_page():
    return send_from_directory(current_app.static_folder, "login.html")


@bp.get("/api/auth/status")
def status():
    user = None
    if session.get("uid"):
        row = get_db().execute("SELECT * FROM users WHERE id = ? AND active = 1", (session["uid"],)).fetchone()
        user = _user_dict(row) if row else None
    return jsonify(user=user, setup_required=_setup_allowed())


def _start_session(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    get_db().execute("UPDATE users SET last_login = ? WHERE id = ?", (now(), user["id"]))
    get_db().commit()


@bp.post("/api/auth/login")
def login():
    ip = _client_ip()
    if _throttled(ip):
        return jsonify(error="Terlalu banyak percobaan gagal. Coba lagi dalam 15 menit."), 429
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not row["active"] or not check_password_hash(row["password_hash"], str(data.get("password", ""))):
        _FAILS[ip].append(time.time())
        return jsonify(error="Email atau password salah"), 401
    _FAILS.pop(ip, None)
    _start_session(row)
    return jsonify(user=_user_dict(row))


@bp.post("/api/auth/setup")
def setup():
    if not _setup_allowed():
        abort(403, "Setup awal sudah dilakukan")
    data = request.get_json(silent=True) or {}
    uid = create_user(get_db(), data.get("email"), data.get("name"), data.get("password"), "admin")
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    _start_session(row)
    return jsonify(user=_user_dict(row)), 201


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/auth/me")
def me():
    return jsonify(_user_dict(g.user))


@bp.post("/api/auth/password")
def change_password():
    data = request.get_json(silent=True) or {}
    if not check_password_hash(g.user["password_hash"], str(data.get("current", ""))):
        abort(400, "Password saat ini salah")
    _validate_password(data.get("new"))
    get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (generate_password_hash(data["new"]), g.user["id"]))
    get_db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- user management (admin)
@bp.get("/api/users")
def list_users():
    rows = get_db().execute("SELECT * FROM users ORDER BY role, email").fetchall()
    return jsonify([_user_dict(r) for r in rows])


@bp.post("/api/users")
def add_user():
    data = request.get_json(silent=True) or {}
    uid = create_user(get_db(), data.get("email"), data.get("name"), data.get("password"),
                      data.get("role", "viewer"))
    return jsonify(_user_dict(get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())), 201


@bp.patch("/api/users/<int:uid>")
def update_user(uid):
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
        abort(404, "Pengguna tidak ditemukan")
    data = request.get_json(silent=True) or {}
    is_self = uid == g.user["id"]
    if "role" in data:
        if data["role"] not in ROLES:
            abort(400, "Peran tidak valid")
        if is_self and data["role"] != "admin":
            abort(400, "Tidak dapat menurunkan peran akun sendiri")
        db.execute("UPDATE users SET role = ? WHERE id = ?", (data["role"], uid))
    if "active" in data:
        if is_self and not data["active"]:
            abort(400, "Tidak dapat menonaktifkan akun sendiri")
        db.execute("UPDATE users SET active = ? WHERE id = ?", (1 if data["active"] else 0, uid))
    if data.get("name"):
        db.execute("UPDATE users SET name = ? WHERE id = ?", (str(data["name"]).strip(), uid))
    if data.get("password"):
        _validate_password(data["password"])
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(data["password"]), uid))
    db.commit()
    return jsonify(_user_dict(db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()))


@bp.errorhandler(400)
@bp.errorhandler(403)
@bp.errorhandler(404)
def _err(e):
    return jsonify(error=e.description), e.code
