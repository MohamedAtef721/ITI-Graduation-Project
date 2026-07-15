"""
utils/scheduler.py
------------------
Monthly Executive Agent.

Runs automatically on the 1st of every month at 08:00 AM.
Steps:
  1. Pull KPIs + top products/customers/suppliers + stock alerts
  2. Generate AI executive summary via the Student Bedrock Gateway
  3. Build the report as a PDF (utils/report_pdf.py)
  4. Send it as an attachment to configured recipients via Gmail SMTP

The scheduler is initialized once when Flask starts (see app.py).
DB/Gmail/model config is read from the .env file at runtime (load_config()).
The SBG_API_KEY itself is read directly from the environment inside
utils/ai_service.py — never from .env-sourced AppConfig fields.
"""

from __future__ import annotations

import datetime as dt
import smtplib
import csv
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ── Module-level scheduler instance ───────────────────────────────────
_scheduler: BackgroundScheduler | None = None


def _get_engine():
    """Get the current DB engine (may be None if not connected yet)."""
    from utils.database import get_engine
    return get_engine()


def _q(sql: str, max_rows: int = 100):
    engine = _get_engine()
    if engine is None:
        return []
    from utils.database import run_query
    try:
        return run_query(sql, max_rows)
    except Exception:
        return []


def _to_csv(rows, n: int = 8) -> str:
    """Used only to build the AI prompt text (not the final report)."""
    if not rows:
        return "(no data)"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows[:n])
    return buf.getvalue()


def _fmt(val, prefix: str = "$") -> str:
    if val is None:
        return "N/A"
    try:
        n = float(val)
        if n >= 1_000_000:
            return f"{prefix}{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{prefix}{n/1_000:.1f}K"
        return f"{prefix}{n:,.2f}"
    except Exception:
        return str(val)


# ── Core monthly job ───────────────────────────────────────────────────

def run_monthly_executive_report(year: int | None = None, month: int | None = None) -> str:
    """
    Generate and send the Monthly Executive Report as a PDF attachment.

    Parameters
    ----------
    year, month : override the target period (default: previous calendar month).

    Returns
    -------
    str : status message ("sent" / "skipped" / error description).
    """
    from utils.config import load_config
    cfg = load_config()

    # If DB not connected yet, skip silently.
    if _get_engine() is None:
        return "skipped: database not connected"

    # Default: previous month
    today = dt.date.today()
    if year is None or month is None:
        first_of_this_month = today.replace(day=1)
        last_month          = first_of_this_month - dt.timedelta(days=1)
        year  = last_month.year
        month = last_month.month

    period = dt.date(year, month, 1).strftime("%B %Y")
    yf     = f"d.YearNumber = {year} AND d.MonthNumber = {month}"

    # ── Queries ──────────────────────────────────────────────────────
    totals = _q(
        f"SELECT SUM(f.LineTotal) AS sales, SUM(f.ProfitAmount) AS profit "
        f"FROM FactSales f JOIN DimDate d ON f.InvoiceDateKey = d.DateKey WHERE {yf}"
    )
    ts = totals[0]["sales"]  if totals else None
    tp = totals[0]["profit"] if totals else None
    margin = f"{tp/ts*100:.1f}%" if ts and tp and float(ts) > 0 else "N/A"

    top_prod = _q(
        f"SELECT TOP 5 dp.Product, SUM(f.LineTotal) AS Revenue "
        f"FROM FactSales f JOIN DimProduct dp ON f.ProductKey=dp.ProductKey "
        f"JOIN DimDate d ON f.InvoiceDateKey=d.DateKey WHERE {yf} "
        f"GROUP BY dp.Product ORDER BY Revenue DESC"
    )
    top_cust = _q(
        f"SELECT TOP 5 dc.CustomerName AS Customer, SUM(f.LineTotal) AS Revenue "
        f"FROM FactSales f JOIN DimCustomer dc ON f.CustomerKey=dc.CustomerKey "
        f"JOIN DimDate d ON f.InvoiceDateKey=d.DateKey WHERE {yf} "
        f"GROUP BY dc.CustomerName ORDER BY Revenue DESC"
    )
    top_sup = _q(
        f"SELECT TOP 5 ds.SupplierName AS Supplier, "
        f"SUM(fp.QuantityOrdered*dp.LastCostPrice*(1+fp.TaxRate/100.0)) AS TotalSpend "
        f"FROM FactPurchases fp JOIN DimSupplier ds ON fp.SupplierKey=ds.SupplierKey "
        f"JOIN DimProduct dp ON fp.ProductKey=dp.ProductKey "
        f"JOIN DimDate d ON fp.PurchaseDateKey=d.DateKey WHERE {yf} "
        f"GROUP BY ds.SupplierName ORDER BY TotalSpend DESC"
    )
    low_stk = _q(
        "SELECT TOP 10 dp.Product, fi.CurrentStock, fi.ReorderLevel "
        "FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey=dp.ProductKey "
        "WHERE fi.CurrentStock <= fi.ReorderLevel ORDER BY fi.CurrentStock ASC"
    )
    overstk = _q(
        "SELECT TOP 10 dp.Product, fi.CurrentStock, fi.TargetStockLevel "
        "FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey=dp.ProductKey "
        "WHERE fi.CurrentStock > fi.TargetStockLevel "
        "ORDER BY (fi.CurrentStock - fi.TargetStockLevel) DESC"
    )

    # ── AI Narrative ─────────────────────────────────────────────────
    # No Flask session exists in the scheduler's background thread, so
    # this uses the session-free Bedrock Gateway helper directly.
    narrative = _generate_narrative_no_session(
        cfg, period, ts, tp,
        top_prod, top_cust, top_sup, low_stk, overstk,
    )

    # ── Build the report PDF ──────────────────────────────────────────
    from utils.report_pdf import build_report_pdf
    pdf_bytes = build_report_pdf(
        period, ts, tp, margin, narrative,
        top_prod, top_cust, top_sup, low_stk, overstk,
    )

    # ── Send email (short body + PDF attachment) ──────────────────────
    if not cfg.gmail_sender or not cfg.gmail_app_password or not cfg.report_recipients:
        return "skipped: email not configured in .env"

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"📦 Smart Inventory — Monthly Executive Report — {period}"
        msg["From"]    = cfg.gmail_sender
        msg["To"]      = ", ".join(cfg.report_recipients)

        body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333">
          <p>📦 <strong>Smart Inventory — Monthly Executive Report — {period}</strong></p>
          <p>Sales: <strong>{_fmt(ts)}</strong> &nbsp;|&nbsp;
             Profit: <strong>{_fmt(tp)}</strong> &nbsp;|&nbsp;
             Margin: <strong>{margin}</strong></p>
          <p>The full report — including top products, customers, suppliers,
             and inventory alerts — is attached as a PDF.</p>
        </body></html>"""
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=f"Smart_Inventory_Report_{period.replace(' ', '_')}.pdf",
        )
        msg.attach(attachment)

        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo()
            s.starttls()
            s.login(cfg.gmail_sender, cfg.gmail_app_password)
            s.sendmail(cfg.gmail_sender, cfg.report_recipients, msg.as_string())

        print(f"[Scheduler] Monthly report for {period} sent to {cfg.report_recipients}")
        return f"sent to {cfg.report_recipients}"

    except Exception as exc:
        print(f"[Scheduler] Email failed: {exc}")
        return f"email error: {exc}"


def _generate_narrative_no_session(cfg, period, ts, tp,
                                   top_prod, top_cust, top_sup,
                                   low_stk, overstk) -> str:
    """
    Generate the AI executive narrative via the Student Bedrock Gateway.
    Runs outside a Flask request, so it uses generate_ai_response_standalone
    (no session access) and picks the model from .env (LLM_MODEL) rather
    than from the live Settings page, since the scheduler has no session
    to read a live selection from.
    """
    from utils.ai_service import generate_ai_response_standalone

    system = (
        "You are a senior BI analyst writing a monthly executive summary "
        "for a wholesale distribution company. Write 6-10 bullet points covering: "
        "sales/profit performance, top products/customers, supplier performance, "
        "inventory risks, and 2-3 concrete recommended actions. "
        "Be specific with numbers and names. "
        "Format with clean Markdown: put each bullet point on its own line."
    )
    user = (
        f"PERIOD: {period}\n"
        f"TOTAL SALES: {ts}\nTOTAL PROFIT: {tp}\n\n"
        f"TOP PRODUCTS:\n{_to_csv(top_prod)}\n\n"
        f"TOP CUSTOMERS:\n{_to_csv(top_cust)}\n\n"
        f"TOP SUPPLIERS:\n{_to_csv(top_sup)}\n\n"
        f"LOW STOCK:\n{_to_csv(low_stk)}\n\n"
        f"OVERSTOCK:\n{_to_csv(overstk)}\n\n"
        "Write the executive summary now:"
    )

    return generate_ai_response_standalone(
        system, user,
        model_id=getattr(cfg, "llm_model", None),
        max_tokens=getattr(cfg, "llm_max_tokens", 2000),
        temperature=0.3,
    )


# ── Scheduler init ─────────────────────────────────────────────────────

def init_scheduler(app):
    """
    Initialize the APScheduler background scheduler.
    Call this once from app.py after creating the Flask app.

    Schedule: 1st of every month at 08:00 AM server time.
    """
    global _scheduler

    if _scheduler is not None:
        return  # already running

    _scheduler = BackgroundScheduler(timezone="Africa/Cairo")

    # Monthly job: 1st of every month at 08:00
    _scheduler.add_job(
        func=run_monthly_executive_report,
        trigger=CronTrigger(day=1, hour=8, minute=0),
        id="monthly_executive_report",
        name="Monthly Executive Report",
        replace_existing=True,
        misfire_grace_time=3600,   # retry up to 1 hour late if server was down
    )

    _scheduler.start()
    print("[Scheduler] Monthly Executive Agent started — fires on 1st of every month at 08:00.")

    # Graceful shutdown when Flask exits
    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False))


def get_scheduler_status() -> dict:
    """Return scheduler status for the API."""
    if _scheduler is None:
        return {"running": False, "jobs": []}
    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id"      : job.id,
            "name"    : job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })
    return {"running": _scheduler.running, "jobs": jobs}