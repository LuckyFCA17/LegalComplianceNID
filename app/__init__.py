"""Legal Compliance NID — register peraturan perundang-undangan & status pemenuhan."""
import os
import secrets
from datetime import timedelta

import click
from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db as dbmod
from .auth import ROLES, bootstrap_admin, create_user
from .sync import ensure_sources, run_sync


def _env_flag(name):
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def _secret_key(db_path):
    """SECRET_KEY from the environment, else a random key persisted next to the database."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=os.environ.get("LCN_DATABASE", os.path.join(app.instance_path, "compliance.db")),
        SEED_ON_START=True,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        # Behind HTTPS (e.g. Render) cookies must be Secure; SameSite=Lax blocks cross-site POSTs (CSRF).
        SESSION_COOKIE_SECURE=_env_flag("LCN_SECURE_COOKIES"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        # When true, the first admin can only come from ADMIN_EMAIL/ADMIN_PASSWORD, never from the browser.
        REQUIRE_ENV_ADMIN=_env_flag("LCN_REQUIRE_ENV_ADMIN"),
    )
    if config:
        app.config.update(config)
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(app.config["DATABASE"])
    if _env_flag("LCN_BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    conn = dbmod.connect(app.config["DATABASE"])
    dbmod.init_db(conn)
    ensure_sources(conn)
    if app.config["SEED_ON_START"] and conn.execute("SELECT COUNT(*) FROM regulations").fetchone()[0] == 0:
        seed = conn.execute("SELECT * FROM sources WHERE code = 'seed'").fetchone()
        run_sync(conn, seed)
    bootstrap_admin(conn)
    conn.close()

    app.teardown_appcontext(dbmod.close_db)

    from .auth import bp as auth_bp
    from .routes import bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)

    @app.cli.command("create-user")
    @click.option("--email", prompt=True)
    @click.option("--name", default="")
    @click.option("--role", type=click.Choice(ROLES), default="admin", show_default=True)
    @click.password_option()
    def create_user_cmd(email, name, role, password):
        """Buat akun pengguna (mis. admin pertama)."""
        try:
            uid = create_user(dbmod.get_db(), email, name, password, role)
        except HTTPException as exc:
            raise click.ClickException(exc.description)
        click.echo(f"Pengguna #{uid} ({role}) dibuat: {email}")

    @app.cli.command("sync")
    @click.option("--source", "sources", multiple=True, help="Kode sumber (seed, bpk, kemnaker, jdihn)")
    @click.option("--category", "categories", multiple=True, help="K3, Lingkungan, Ketenagakerjaan")
    def sync_cmd(sources, categories):
        """Sinkronkan database peraturan dari sumber JDIH."""
        db = dbmod.get_db()
        if sources:
            rows = [db.execute("SELECT * FROM sources WHERE code = ?", (s,)).fetchone() for s in sources]
            rows = [r for r in rows if r]
        else:
            rows = db.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
        for r in rows:
            res = run_sync(db, r, list(categories) or None)
            click.echo(f"[{res['status']}] {r['name']}: {res['message']}")

    return app
