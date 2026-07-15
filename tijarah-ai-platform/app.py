"""
app.py — Smart Inventory Copilot (Flask)
"""

import os
from flask import Flask, render_template, session
from flask_session import Session
from api.routes import api_bp
from utils.config import load_config
from utils.database import connect
from utils.scheduler import init_scheduler

app = Flask(__name__)
app.secret_key = "smart_inventory_secret_2025"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Register API blueprint
app.register_blueprint(api_bp, url_prefix="/api")

# Start Monthly Executive Agent scheduler
init_scheduler(app)


# ── Auto-connect to the database on startup ─────────────────────────────
# utils/database._engine is an in-memory variable — it resets to None on
# every server restart, even though the Flask session (stored on disk via
# SESSION_TYPE="filesystem") survives restarts and keeps saying
# "connected": True. That mismatch was causing pages like Forecasting to
# silently get empty results after a restart, while the sidebar still
# showed "Connected", until someone reopened Settings and clicked
# "Connect & Save" again.
#
# This attempts the same connection using the DB credentials already
# stored in .env (via load_config()), right when the app boots, so a
# restart doesn't require a manual reconnect. If the DB isn't reachable
# yet (e.g. SQL Server not started), it logs a warning instead of
# crashing the app — the Settings page can still be used to connect
# manually afterward.
#
# Guarded against Werkzeug's debug reloader, which re-executes this
# module in a subprocess: without the guard, this would attempt to
# connect twice on every debug-mode start.
def _auto_connect_on_startup():
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        try:
            cfg = load_config()
            connect(cfg)
            print(f"[Startup] Auto-connected to database '{cfg.db_name}' on '{cfg.db_server}'.")
        except Exception as exc:
            print(f"[Startup] Auto-connect skipped — could not reach the database yet: {exc}")
            print("[Startup] Go to Settings and click 'Connect & Save' once the database is reachable.")

_auto_connect_on_startup()


# ── Page routes ────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/sales")
def sales():
    return render_template("sales.html")

@app.route("/inventory")
def inventory():
    return render_template("inventory.html")

@app.route("/purchasing")
def purchasing():
    return render_template("purchasing.html")

@app.route("/ai-advisor")
def ai_advisor():
    return render_template("ai_advisor.html")

@app.route("/forecasting")
def forecasting():
    return render_template("forecasting.html")

@app.route("/report")
def report():
    return render_template("report.html")

@app.route("/settings")
def settings():
    return render_template("settings.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)