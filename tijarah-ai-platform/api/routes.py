"""
api/routes.py
-------------
All REST API endpoints consumed by the frontend JS.
"""

from __future__ import annotations
import re, json, smtplib, datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, request, jsonify, session
from utils.database import connect, run_query, get_schema, get_engine
from utils.config import load_config, AppConfig
from utils.ai_service import (
    run_agent, generate_ai_response,
    get_memory, get_biz_memory, update_biz_memory,
)

api_bp = Blueprint("api", __name__)

# ── helpers ────────────────────────────────────────────────────────────

def _cfg() -> AppConfig:
    raw = session.get("config")
    if raw:
        cfg = AppConfig(**{k: v for k, v in raw.items()
                          if k in AppConfig.__dataclass_fields__})
        cfg.report_recipients = raw.get("report_recipients", [])
        return cfg
    return load_config()

def _q(sql, max_rows=2000):
    try:
        return run_query(sql, max_rows)
    except Exception as exc:
        return {"error": str(exc)}

def _scalar(sql):
    rows = _q(sql, max_rows=1)
    if isinstance(rows, dict) or not rows:
        return None
    return list(rows[0].values())[0]

# ── Settings ───────────────────────────────────────────────────────────

@api_bp.route("/connect", methods=["POST"])
def api_connect():
    data = request.json or {}
    recipients = [r.strip() for r in data.get("report_recipients","").split(",") if r.strip()]

    # AI model is selected here; the student API key itself is never sent
    # from the frontend — it's read server-side from the SBG_API_KEY
    # environment variable inside utils/ai_service.py.
    llm_model      = data.get("llm_model", "anthropic.claude-sonnet-4-6")
    llm_max_tokens = int(data.get("llm_max_tokens", 1000))

    # Strip ALL whitespace (including non-breaking spaces, \xa0) from the
    # Gmail App Password. Google's account page displays it in 4-char
    # groups separated by non-breaking spaces, which get copied along
    # with the password and crash smtplib's ASCII-only AUTH PLAIN login.
    gmail_sender       = re.sub(r"\s+", "", data.get("gmail_sender","") or "")
    gmail_app_password = re.sub(r"\s+", "", data.get("gmail_app_password","") or "")

    cfg = AppConfig(
        db_server          = data.get("db_server","localhost"),
        db_name            = data.get("db_name","SmartInventory_DWH"),
        db_driver          = data.get("db_driver","ODBC Driver 17 for SQL Server"),
        db_trusted         = data.get("db_trusted", True),
        db_username        = data.get("db_username",""),
        db_password        = data.get("db_password",""),
        gmail_sender       = gmail_sender,
        gmail_app_password = gmail_app_password,
        report_recipients  = recipients,
    )
    try:
        connect(cfg)
        schema = get_schema()
        session["config"] = {
            "db_server"        : cfg.db_server,
            "db_name"          : cfg.db_name,
            "db_driver"        : cfg.db_driver,
            "db_trusted"       : cfg.db_trusted,
            "db_username"      : cfg.db_username,
            "db_password"      : cfg.db_password,
            "gmail_sender"     : cfg.gmail_sender,
            "gmail_app_password": cfg.gmail_app_password,
            "report_recipients": recipients,
            # Student Bedrock Gateway: model selection only (no key here)
            "llm_model"        : llm_model,
            "llm_max_tokens"   : llm_max_tokens,
        }
        session["connected"] = True
        return jsonify({"ok": True, "tables": len(schema), "schema": schema})
    except Exception as exc:
        session["connected"] = False
        return jsonify({"ok": False, "error": str(exc)}), 400

@api_bp.route("/status")
def api_status():
    cfg_raw = session.get("config", {})
    # Check the REAL engine, not just the session flag — session["connected"]
    # can still say True after a server restart even though the in-memory
    # DB engine (utils/database._engine) reset to None, which is what was
    # causing pages like Forecasting to silently get empty results while
    # the sidebar still showed "Connected".
    engine = get_engine()
    is_connected = engine is not None
    if is_connected != session.get("connected", False):
        session["connected"] = is_connected
    return jsonify({
        "connected": is_connected,
        "config": {
            "llm_model": cfg_raw.get("llm_model", "—"),
        }
    })

@api_bp.route("/schema")
def api_schema():
    return jsonify(get_schema())


# ── Scheduler ─────────────────────────────────────────────────────────

@api_bp.route("/scheduler/status")
def api_scheduler_status():
    from utils.scheduler import get_scheduler_status
    return jsonify(get_scheduler_status())


@api_bp.route("/scheduler/run-now", methods=["POST"])
def api_scheduler_run_now():
    """Manually trigger the monthly executive report (for testing)."""
    from utils.scheduler import run_monthly_executive_report
    data  = request.json or {}
    year  = data.get("year")
    month = data.get("month")
    try:
        result = run_monthly_executive_report(
            year=int(year)   if year  else None,
            month=int(month) if month else None,
        )
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

# ── Home KPIs ─────────────────────────────────────────────────────────

@api_bp.route("/kpis")
def api_kpis():
    total_sales   = _scalar("SELECT SUM(LineTotal) FROM FactSales")
    total_profit  = _scalar("SELECT SUM(ProfitAmount) FROM FactSales")
    total_orders  = _scalar("SELECT COUNT(DISTINCT InvoiceID) FROM FactSales")
    total_purchases = _scalar("""
        SELECT SUM(fp.QuantityOrdered * dp.LastCostPrice * (1 + fp.TaxRate/100.0))
        FROM FactPurchases fp JOIN DimProduct dp ON fp.ProductKey = dp.ProductKey
    """)
    low_stock_count = _scalar("""
        SELECT COUNT(*) FROM FactInventory
        WHERE CurrentStock <= ReorderLevel
    """)
    margin = round(total_profit / total_sales * 100, 1) if total_sales and total_profit and total_sales > 0 else None
    return jsonify({
        "total_sales"     : total_sales,
        "total_profit"    : total_profit,
        "total_orders"    : total_orders,
        "total_purchases" : total_purchases,
        "profit_margin"   : margin,
        "low_stock_count" : low_stock_count,
    })

@api_bp.route("/home/trend")
def api_home_trend():
    rows = _q("""
        SELECT d.MonthName + ' ' + CAST(d.YearNumber AS VARCHAR) AS period,
               d.YearNumber AS yr, d.MonthNumber AS mo,
               SUM(f.LineTotal) AS revenue
        FROM FactSales f JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        GROUP BY d.YearNumber, d.MonthNumber, d.MonthName
        ORDER BY d.YearNumber, d.MonthNumber
    """)
    return jsonify(rows)

@api_bp.route("/home/top-products")
def api_home_top_products():
    rows = _q("""
        SELECT TOP 8 dp.Product, SUM(f.LineTotal) AS revenue
        FROM FactSales f JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
        GROUP BY dp.Product ORDER BY revenue DESC
    """)
    return jsonify(rows)

@api_bp.route("/home/alerts")
def api_home_alerts():
    rows = _q("""
        SELECT TOP 5 dp.Product, fi.CurrentStock, fi.ReorderLevel,
               (fi.ReorderLevel - fi.CurrentStock) AS deficit
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        WHERE fi.CurrentStock <= fi.ReorderLevel
        ORDER BY deficit DESC
    """)
    return jsonify(rows)

# ── Sales ──────────────────────────────────────────────────────────────

@api_bp.route("/sales/trend")
def api_sales_trend():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT d.MonthName + ' ' + CAST(d.YearNumber AS VARCHAR) AS period,
               d.YearNumber AS yr, d.MonthNumber AS mo,
               SUM(f.LineTotal) AS revenue, SUM(f.ProfitAmount) AS profit
        FROM FactSales f JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        WHERE 1=1 {yf}
        GROUP BY d.YearNumber, d.MonthNumber, d.MonthName
        ORDER BY d.YearNumber, d.MonthNumber
    """)
    return jsonify(rows)

@api_bp.route("/sales/top-products")
def api_sales_top_products():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT TOP 10 dp.Product, SUM(f.LineTotal) AS revenue, SUM(f.ProfitAmount) AS profit
        FROM FactSales f JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
        JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        WHERE 1=1 {yf}
        GROUP BY dp.Product ORDER BY revenue DESC
    """)
    return jsonify(rows)

@api_bp.route("/sales/top-customers")
def api_sales_top_customers():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT TOP 10 dc.CustomerName AS customer, SUM(f.LineTotal) AS revenue
        FROM FactSales f JOIN DimCustomer dc ON f.CustomerKey = dc.CustomerKey
        JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        WHERE 1=1 {yf}
        GROUP BY dc.CustomerName ORDER BY revenue DESC
    """)
    return jsonify(rows)

@api_bp.route("/sales/by-category")
def api_sales_by_category():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT dp.Category, SUM(f.LineTotal) AS revenue, SUM(f.ProfitAmount) AS profit
        FROM FactSales f JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
        JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        WHERE 1=1 {yf}
        GROUP BY dp.Category ORDER BY revenue DESC
    """)
    return jsonify(rows)

@api_bp.route("/sales/years")
def api_sales_years():
    rows = _q("SELECT DISTINCT YearNumber AS year FROM DimDate ORDER BY YearNumber DESC")
    return jsonify(rows)

# ── Inventory ──────────────────────────────────────────────────────────

@api_bp.route("/inventory/low-stock")
def api_low_stock():
    rows = _q("""
        SELECT TOP 20 dp.Product, fi.CurrentStock, fi.ReorderLevel,
               (fi.ReorderLevel - fi.CurrentStock) AS deficit
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        WHERE fi.CurrentStock <= fi.ReorderLevel ORDER BY deficit DESC
    """)
    return jsonify(rows)

@api_bp.route("/inventory/overstock")
def api_overstock():
    rows = _q("""
        SELECT TOP 20 dp.Product, fi.CurrentStock, fi.TargetStockLevel,
               (fi.CurrentStock - fi.TargetStockLevel) AS excess
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        WHERE fi.CurrentStock > fi.TargetStockLevel ORDER BY excess DESC
    """)
    return jsonify(rows)

@api_bp.route("/inventory/value-by-category")
def api_inv_value_by_cat():
    rows = _q("""
        SELECT dp.Category,
               SUM(CAST(fi.CurrentStock AS FLOAT)*CAST(fi.LastCostPrice AS FLOAT)) AS inv_value
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        GROUP BY dp.Category ORDER BY inv_value DESC
    """)
    return jsonify(rows)

# ── Purchasing ─────────────────────────────────────────────────────────

@api_bp.route("/purchasing/top-suppliers")
def api_top_suppliers():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT TOP 10 ds.SupplierName AS supplier,
               SUM(fp.QuantityOrdered * dp.LastCostPrice * (1 + fp.TaxRate/100.0)) AS total_spend,
               COUNT(DISTINCT fp.PurchaseOrderID) AS orders
        FROM FactPurchases fp JOIN DimSupplier ds ON fp.SupplierKey = ds.SupplierKey
        JOIN DimProduct dp ON fp.ProductKey = dp.ProductKey
        JOIN DimDate d ON fp.PurchaseDateKey = d.DateKey
        WHERE 1=1 {yf}
        GROUP BY ds.SupplierName ORDER BY total_spend DESC
    """)
    return jsonify(rows)

@api_bp.route("/purchasing/trend")
def api_purchase_trend():
    yr = request.args.get("year","")
    yf = f"AND d.YearNumber = {yr}" if yr and yr != "All" else ""
    rows = _q(f"""
        SELECT d.MonthName + ' ' + CAST(d.YearNumber AS VARCHAR) AS period,
               d.YearNumber AS yr, d.MonthNumber AS mo,
               SUM(fp.QuantityOrdered * dp.LastCostPrice * (1 + fp.TaxRate/100.0)) AS total_cost
        FROM FactPurchases fp JOIN DimDate d ON fp.PurchaseDateKey = d.DateKey
        JOIN DimProduct dp ON fp.ProductKey = dp.ProductKey
        WHERE 1=1 {yf}
        GROUP BY d.YearNumber, d.MonthNumber, d.MonthName
        ORDER BY d.YearNumber, d.MonthNumber
    """)
    return jsonify(rows)

@api_bp.route("/purchasing/top-products")
def api_purchase_top_products():
    rows = _q("""
        SELECT TOP 10 dp.Product, SUM(fp.QuantityOrdered) AS qty,
               SUM(fp.QuantityOrdered * dp.LastCostPrice * (1 + fp.TaxRate/100.0)) AS total_cost
        FROM FactPurchases fp JOIN DimProduct dp ON fp.ProductKey = dp.ProductKey
        GROUP BY dp.Product ORDER BY total_cost DESC
    """)
    return jsonify(rows)

# ── AI Advisor ─────────────────────────────────────────────────────────

@api_bp.route("/ai/ask", methods=["POST"])
def api_ai_ask():
    data     = request.json or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    schema = get_schema()
    engine = get_engine()

    result = run_agent(question, schema, engine)
    return jsonify(result)


@api_bp.route("/ai/memory")
def api_ai_memory():
    return jsonify({
        "conversation": get_memory(),
        "business"    : get_biz_memory(),
    })


@api_bp.route("/ai/memory/clear", methods=["POST"])
def api_clear_memory():
    session.pop("conv_memory", None)
    session.pop("biz_memory",  None)
    session.modified = True
    return jsonify({"ok": True})


@api_bp.route("/ai/logs")
def api_logs():
    from pathlib import Path
    import json
    log_path = Path(__file__).parent.parent / "logs" / "agent_log.json"
    try:
        with open(log_path) as f:
            logs = json.load(f)
        return jsonify(logs[-50:])  # last 50
    except Exception:
        return jsonify([])

# ── Forecasting ────────────────────────────────────────────────────────

@api_bp.route("/forecast/products")
def api_forecast_products():
    rows = _q("""
        SELECT DISTINCT dp.ProductKey, dp.Product AS product_name
        FROM DimProduct dp JOIN FactSales fs ON dp.ProductKey = fs.ProductKey
        ORDER BY dp.Product
    """, max_rows=5000)
    return jsonify(rows)

@api_bp.route("/forecast/run", methods=["POST"])
def api_forecast_run():
    data        = request.json or {}
    product_key = data.get("product_key")
    horizon     = int(data.get("horizon_months", 3))

    pf = f"AND fs.ProductKey = {int(product_key)}" if product_key else ""
    rows = run_query(f"""
        SELECT CAST(d.FullDate AS DATE) AS ds, SUM(fs.LineTotal) AS y
        FROM FactSales fs JOIN DimDate d ON fs.InvoiceDateKey = d.DateKey
        WHERE 1=1 {pf}
        GROUP BY d.FullDate ORDER BY d.FullDate
    """, max_rows=100000)

    if not rows or len(rows) < 10:
        return jsonify({"error": "Not enough historical data (need ≥ 10 points)"}), 400

    try:
        import pandas as pd, logging
        logging.getLogger("prophet").setLevel(logging.WARNING)
        logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
        from prophet import Prophet

        df = pd.DataFrame(rows)
        df["ds"] = pd.to_datetime(df["ds"])
        df["y"]  = pd.to_numeric(df["y"], errors="coerce").fillna(0)

        model = Prophet(yearly_seasonality=True, weekly_seasonality=True,
                        daily_seasonality=False, interval_width=0.80)
        model.fit(df)
        future   = model.make_future_dataframe(periods=int(horizon * 30.44), freq="D")
        forecast = model.predict(future)[["ds","yhat","yhat_lower","yhat_upper"]]
        forecast["ds"] = forecast["ds"].dt.strftime("%Y-%m-%d")

        last_date     = df["ds"].max()
        future_mask   = pd.to_datetime(forecast["ds"]) > last_date
        future_part   = forecast.loc[future_mask]
        horizon_days  = int(horizon * 30.44)
        recent_cutoff = last_date - pd.Timedelta(days=horizon_days)
        recent_actual = float(df.loc[df["ds"] > recent_cutoff, "y"].sum())
        forecast_total= float(future_part["yhat"].clip(lower=0).sum())
        pct_change    = round((forecast_total-recent_actual)/recent_actual*100, 1) if recent_actual > 0 else None
        trend         = "up" if (pct_change or 0) > 5 else ("down" if (pct_change or 0) < -5 else "flat")

        # Sanity flag: real quarter-over-quarter business growth is
        # essentially never triple-digit percent without an extraordinary
        # one-off event. A jump this large almost always signals a data
        # quality issue (e.g. an inflated/incomplete period in the
        # underlying sales history) rather than a genuine forecast — flag
        # it so the UI can warn instead of presenting it as fact.
        implausible_growth = pct_change is not None and abs(pct_change) > 100

        # AI interpretation
        avg_lo = float(future_part["yhat_lower"].clip(lower=0).sum())
        avg_hi = float(future_part["yhat_upper"].clip(lower=0).sum())
        narrative = generate_ai_response(
            "You are a senior business analyst. Explain this sales forecast in plain language "
            "and give 2-3 business recommendations. Reply in English. Never invent numbers.",
            f"HORIZON: {horizon} months\n"
            f"RECENT ACTUAL: {recent_actual:,.2f}\n"
            f"FORECAST: {forecast_total:,.2f}\n"
            f"CONFIDENCE: {avg_lo:,.2f} — {avg_hi:,.2f}\n"
            f"CHANGE: {pct_change}%\nTREND: {trend}\n\nWrite summary and recommendations:"
        )

        history_out  = df[["ds","y"]].copy()
        history_out["ds"] = history_out["ds"].dt.strftime("%Y-%m-%d")

        return jsonify({
            "history"       : history_out.to_dict("records"),
            "forecast"      : forecast.to_dict("records"),
            "recent_actual" : recent_actual,
            "forecast_total": forecast_total,
            "pct_change"    : pct_change,
            "trend"         : trend,
            "narrative"     : narrative,
            "implausible_growth": implausible_growth,
        })

    except ImportError:
        return jsonify({"error": "Prophet not installed. Run: pip install prophet"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

# ── Monthly Report ─────────────────────────────────────────────────────

@api_bp.route("/report/generate", methods=["POST"])
def api_report_generate():
    data  = request.json or {}
    year  = int(data.get("year",  dt.date.today().year))
    month = int(data.get("month", dt.date.today().month))
    yf    = f"d.YearNumber = {year} AND d.MonthNumber = {month}"

    totals   = _q(f"SELECT SUM(f.LineTotal) AS sales, SUM(f.ProfitAmount) AS profit FROM FactSales f JOIN DimDate d ON f.InvoiceDateKey = d.DateKey WHERE {yf}")
    ts = totals[0]["sales"]  if totals else None
    tp = totals[0]["profit"] if totals else None
    margin = f"{tp/ts*100:.1f}%" if ts and tp and ts > 0 else "N/A"

    top_prod = _q(f"SELECT TOP 5 dp.Product, SUM(f.LineTotal) AS revenue FROM FactSales f JOIN DimProduct dp ON f.ProductKey=dp.ProductKey JOIN DimDate d ON f.InvoiceDateKey=d.DateKey WHERE {yf} GROUP BY dp.Product ORDER BY revenue DESC")
    top_cust = _q(f"SELECT TOP 5 dc.CustomerName AS customer, SUM(f.LineTotal) AS revenue FROM FactSales f JOIN DimCustomer dc ON f.CustomerKey=dc.CustomerKey JOIN DimDate d ON f.InvoiceDateKey=d.DateKey WHERE {yf} GROUP BY dc.CustomerName ORDER BY revenue DESC")
    top_sup  = _q(f"SELECT TOP 5 ds.SupplierName AS supplier, SUM(fp.QuantityOrdered*dp.LastCostPrice*(1+fp.TaxRate/100.0)) AS spend FROM FactPurchases fp JOIN DimSupplier ds ON fp.SupplierKey=ds.SupplierKey JOIN DimProduct dp ON fp.ProductKey=dp.ProductKey JOIN DimDate d ON fp.PurchaseDateKey=d.DateKey WHERE {yf} GROUP BY ds.SupplierName ORDER BY spend DESC")
    low_stk  = _q("SELECT TOP 10 dp.Product, fi.CurrentStock, fi.ReorderLevel FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey=dp.ProductKey WHERE fi.CurrentStock<=fi.ReorderLevel ORDER BY fi.CurrentStock ASC")
    overstk  = _q("SELECT TOP 10 dp.Product, fi.CurrentStock, fi.TargetStockLevel FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey=dp.ProductKey WHERE fi.CurrentStock>fi.TargetStockLevel ORDER BY (fi.CurrentStock-fi.TargetStockLevel) DESC")

    def to_csv(rows, n=8):
        if not rows: return "(no data)"
        import csv, io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows[:n])
        return buf.getvalue()

    period = dt.date(year, month, 1).strftime("%B %Y")
    narrative = generate_ai_response(
        "You are a senior BI analyst. Write a professional monthly executive summary "
        "(6-10 bullets): sales/profit, top products/customers, supplier performance, "
        "inventory risks, 2-3 recommended actions. Be specific with numbers and names.",
        f"PERIOD: {period}\nSALES: {ts}\nPROFIT: {tp}\n\n"
        f"TOP PRODUCTS:\n{to_csv(top_prod)}\nTOP CUSTOMERS:\n{to_csv(top_cust)}\n"
        f"TOP SUPPLIERS:\n{to_csv(top_sup)}\nLOW STOCK:\n{to_csv(low_stk)}\n"
        f"OVERSTOCK:\n{to_csv(overstk)}\n\nWrite the summary:"
    )

    return jsonify({
        "period": period, "total_sales": ts, "total_profit": tp, "margin": margin,
        "top_products": top_prod, "top_customers": top_cust, "top_suppliers": top_sup,
        "low_stock": low_stk, "overstock": overstk, "narrative": narrative,
    })

@api_bp.route("/report/send-email", methods=["POST"])
def api_send_email():
    data = request.json or {}
    cfg  = _cfg()
    if not cfg.gmail_sender or not cfg.gmail_app_password or not cfg.report_recipients:
        return jsonify({"error": "Email not configured in Settings"}), 400

    period        = data.get("period", "")
    total_sales   = data.get("total_sales")
    total_profit  = data.get("total_profit")
    margin        = data.get("margin", "N/A")
    narrative     = data.get("narrative", "")
    top_products  = data.get("top_products", [])
    top_customers = data.get("top_customers", [])
    top_suppliers = data.get("top_suppliers", [])
    low_stock     = data.get("low_stock", [])
    overstock     = data.get("overstock", [])

    try:
        from utils.report_pdf import build_report_pdf
        pdf_bytes = build_report_pdf(
            period, total_sales, total_profit, margin, narrative,
            top_products, top_customers, top_suppliers, low_stock, overstock,
        )

        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"📦 Smart Inventory Report — {period}"
        msg["From"]    = cfg.gmail_sender
        msg["To"]      = ", ".join(cfg.report_recipients)

        def _fmt_short(val, prefix="$"):
            if val is None:
                return "N/A"
            try:
                n = float(val)
                if n >= 1_000_000: return f"{prefix}{n/1_000_000:.1f}M"
                if n >= 1_000:     return f"{prefix}{n/1_000:.1f}K"
                return f"{prefix}{n:,.2f}"
            except Exception:
                return str(val)

        body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333">
          <p>📦 <strong>Smart Inventory Report — {period}</strong></p>
          <p>Sales: <strong>{_fmt_short(total_sales)}</strong> &nbsp;|&nbsp;
             Profit: <strong>{_fmt_short(total_profit)}</strong> &nbsp;|&nbsp;
             Margin: <strong>{margin}</strong></p>
          <p>The full report is attached as a PDF.</p>
        </body></html>"""
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        from email.mime.application import MIMEApplication
        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=f"Smart_Inventory_Report_{period.replace(' ', '_') or 'report'}.pdf",
        )
        msg.attach(attachment)

        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls()
            s.login(cfg.gmail_sender, cfg.gmail_app_password)
            s.sendmail(cfg.gmail_sender, cfg.report_recipients, msg.as_string())
        return jsonify({"ok": True, "sent_to": cfg.report_recipients})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500