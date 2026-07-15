"""
utils/powerbi_desktop_service.py
----------------------------------
Local-only connection to a Power BI Desktop file that is currently OPEN
on this same machine. Power BI Desktop runs a local Analysis Services
(SSAS Tabular) engine in the background while a .pbix file is open,
listening on a dynamic localhost port — this connects to that engine
and runs real DAX queries against it.

IMPORTANT LIMITATIONS (read before using):
  - Only works while Power BI Desktop is open with the report loaded,
    on the SAME machine running this Flask app. Closing Desktop breaks
    the connection immediately.
  - The port changes every time you reopen the .pbix file — you must
    re-find it (see below) after every restart of Power BI Desktop.
  - This is a local development/demo convenience, NOT a substitute for
    publishing to Power BI Service (utils/powerbi_service.py) for any
    real/production deployment — a real deployment can't rely on a
    developer's laptop having Power BI Desktop open.

Setup:
  1. Install the ADOMD.NET client libraries (Microsoft SQL Server
     Feature Pack — search "AMO ADOMD.NET" from Microsoft's download
     center) — pyadomd wraps this .NET library.
  2. pip install pyadomd
  3. Open your .pbix file in Power BI Desktop and leave it open.
  4. Find the local port: open DAX Studio (daxstudio.org) — it
     auto-detects open Power BI Desktop instances and shows a
     connection string like "localhost:52562". Copy that port number.
  5. Set it in .env:
       POWERBI_DESKTOP_PORT=52562
     (or pass it directly to the functions below)
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_connection_string(port: int | None = None) -> str | None:
    port = port or os.environ.get("POWERBI_DESKTOP_PORT")
    if not port:
        return None
    return f"Provider=MSOLAP;Data Source=localhost:{port};"


def is_configured() -> bool:
    return bool(os.environ.get("POWERBI_DESKTOP_PORT"))


def run_dax_query(dax_query: str, port: int | None = None) -> list[dict] | None:
    """
    Execute a DAX query against the locally-open Power BI Desktop file.
    Returns None if pyadomd isn't installed, no port is configured, or
    the connection fails (e.g. Power BI Desktop isn't open) — callers
    should treat None as "not available right now" and fall back.
    """
    conn_str = _get_connection_string(port)
    if not conn_str:
        return None

    try:
        from pyadomd import Pyadomd
    except ImportError:
        return None

    try:
        with Pyadomd(conn_str) as conn:
            with conn.cursor().execute(dax_query) as cur:
                columns = [d[0] for d in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception:
        return None


def get_measure(measure_name: str, port: int | None = None) -> float | None:
    """Fetch a single DAX measure's current value from the open .pbix file."""
    dax = f'EVALUATE ROW("{measure_name}", [{measure_name}])'
    rows = run_dax_query(dax, port=port)
    if not rows:
        return None
    for key, value in rows[0].items():
        if measure_name in key:
            return value
    return None


def build_powerbi_desktop_snapshot(measure_names: list[str], port: int | None = None) -> str:
    """Same shape as build_powerbi_snapshot() in powerbi_service.py, but
    sourced from the locally-open Power BI Desktop file instead of a
    published dataset. Returns "" if unavailable so callers can safely
    fall back to another context source."""
    if not (is_configured() or port):
        return ""

    lines = ["LIVE POWER BI DESKTOP MEASURES (from the .pbix file currently open on this machine):"]
    got_any = False
    for name in measure_names:
        val = get_measure(name, port=port)
        if val is not None:
            lines.append(f"- {name}: {val}")
            got_any = True

    return "\n".join(lines) if got_any else ""
