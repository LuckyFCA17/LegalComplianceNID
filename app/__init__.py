"""Legal Compliance NID — register peraturan perundang-undangan & status pemenuhan."""
import os

import click
from flask import Flask

from . import db as dbmod
from .sync import ensure_sources, run_sync


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=os.environ.get("LCN_DATABASE", os.path.join(app.instance_path, "compliance.db")),
        SEED_ON_START=True,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)

    conn = dbmod.connect(app.config["DATABASE"])
    dbmod.init_db(conn)
    ensure_sources(conn)
    if app.config["SEED_ON_START"] and conn.execute("SELECT COUNT(*) FROM regulations").fetchone()[0] == 0:
        seed = conn.execute("SELECT * FROM sources WHERE code = 'seed'").fetchone()
        run_sync(conn, seed)
    conn.close()

    app.teardown_appcontext(dbmod.close_db)

    from .routes import bp
    app.register_blueprint(bp)

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
