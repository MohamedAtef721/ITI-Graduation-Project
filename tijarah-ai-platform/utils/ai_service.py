"""
utils/ai_service.py
--------------------
Unified AI service layer for Smart Inventory Copilot.

Provides:
- LLM access via the ITI Student Bedrock Gateway (SBG)
- Conversation memory (last 10 interactions)
- Business memory (top customer/supplier/product/forecast)
- SQL schema validation + auto-retry
- Agent-like intent routing
- Structured logging to logs/agent_log.json
"""

from __future__ import annotations

import json
import os
import re
import time
import datetime as dt
from pathlib import Path
from typing import Optional

import requests
from flask import session

# Load variables from a local .env file if python-dotenv is installed.
# This lets you keep SBG_API_KEY in a .env file instead of exporting it
# manually every time. Safe to skip if the package isn't installed.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Log file ──────────────────────────────────────────────────────────
LOG_PATH = Path(__file__).parent.parent / "logs" / "agent_log.json"


def _append_log(entry: dict):
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        logs = []
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.append(entry)
        # Keep last 500 entries
        if len(logs) > 500:
            logs = logs[-500:]
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        pass


# ── Student Bedrock Gateway (SBG) config ───────────────────────────────
# IMPORTANT: never hardcode the student API key in source code.
# Before running the app, export it once in your shell / .env file:
#   export SBG_API_KEY="sbg_xxxxxxxxxxxxxxxx"
#
# If your actual gateway host differs from the default below, override it
# with an env var instead of editing this file:
#   export SBG_BASE_URL="http://apiaccess.iti.net.eg/api/v1"
SBG_BASE_URL = os.environ.get("SBG_BASE_URL", "http://apiaccess.iti.net.eg/api/v1").rstrip("/")
SBG_CHAT_ENDPOINT = f"{SBG_BASE_URL}/student/chat"

# Pick any model_id from your student dashboard. This is just the fallback
# used when nothing is set in session config (Settings page).
SBG_DEFAULT_MODEL = "anthropic.claude-sonnet-4-6"


def _extract_text(data: dict) -> str:
    """
    The Student Bedrock Gateway normalizes every model's response to a
    single `output_text` field, regardless of which underlying model
    (Anthropic, OpenAI gpt-oss, Llama, DeepSeek, etc.) handled the request.
    Example shape:
        {"request_id": "...", "model_id": "...", "output_text": "...",
         "usage": {...}, "status": "active"}
    """
    output_text = data.get("output_text")

    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    # output_text present but empty — almost always means the model ran
    # out of token budget (reasoning models like gpt-oss spend tokens on
    # hidden chain-of-thought before writing visible output).
    if "output_text" in data:
        usage = data.get("usage", {}) or {}
        if usage.get("stop_reason") == "max_tokens":
            return (
                "AI returned an empty response: it ran out of token budget "
                "before producing an answer (common with reasoning models "
                "like gpt-oss). Try increasing max_tokens in Settings, or "
                "switch to a non-reasoning model."
            )
        return "AI returned an empty response."

    # Fallback shapes, kept for safety in case a different endpoint or
    # model family returns a different structure.
    try:
        if isinstance(data.get("content"), list):
            parts = [
                b.get("text", "") for b in data["content"]
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            if parts:
                return "\n".join(parts).strip()

        if isinstance(data.get("choices"), list) and data["choices"]:
            msg = data["choices"][0].get("message", {})
            if isinstance(msg.get("content"), str):
                return msg["content"].strip()

        for key in ("answer", "response", "text", "output", "result"):
            if isinstance(data.get(key), str):
                return data[key].strip()

        if isinstance(data.get("message"), dict) and isinstance(data["message"].get("content"), str):
            return data["message"]["content"].strip()

    except Exception:
        pass

    # Fallback: show the raw payload (truncated) so failures are debuggable
    return json.dumps(data, ensure_ascii=False)[:1000]


def _call_bedrock_gateway(api_key: str, model_id: str, system: str,
                           user: str, temperature: float,
                           max_tokens: int = 1000) -> str:
    """Call the Student Bedrock Gateway /student/chat endpoint."""
    payload = {
        "model_id": model_id,
        "messages": [
            {"role": "user", "content": user}
        ],
        "system_prompt": system,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(
            SBG_CHAT_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return f"SBG Gateway error: {exc}"

    try:
        data = resp.json()
    except ValueError:
        return f"SBG Gateway returned a non-JSON response: {resp.text[:300]}"

    return _extract_text(data)


def generate_ai_response(system_prompt: str, user_prompt: str,
                         temperature: float = 0.1) -> str:
    """
    Send a prompt to the Student Bedrock Gateway.
    The model_id is read from Flask session config (Settings page),
    falling back to SBG_DEFAULT_MODEL. The student API key is read
    from the SBG_API_KEY environment variable (never from session).

    NOTE: requires an active Flask request/session context. For code
    that runs outside a request (e.g. the APScheduler background job
    in utils/scheduler.py), use generate_ai_response_standalone instead.
    """
    cfg_raw    = session.get("config", {})
    model_id   = cfg_raw.get("llm_model") or SBG_DEFAULT_MODEL
    max_tokens = int(cfg_raw.get("llm_max_tokens", 2000))

    return generate_ai_response_standalone(
        system_prompt, user_prompt,
        model_id=model_id, max_tokens=max_tokens, temperature=temperature,
    )


def generate_ai_response_standalone(system_prompt: str, user_prompt: str,
                                     model_id: str | None = None,
                                     max_tokens: int = 2000,
                                     temperature: float = 0.1) -> str:
    """
    Session-free version of generate_ai_response. Use this from code that
    runs outside a Flask request context — e.g. the monthly scheduler job
    in utils/scheduler.py, which has no session to read a model from.
    Pass model_id explicitly (e.g. from AppConfig.llm_model, sourced from
    .env) or rely on SBG_DEFAULT_MODEL.
    """
    model_id = model_id or SBG_DEFAULT_MODEL

    api_key = os.environ.get("SBG_API_KEY", "")
    if not api_key:
        return "SBG_API_KEY is not set. Export it as an environment variable before starting the app."

    return _call_bedrock_gateway(
        api_key, model_id, system_prompt, user_prompt, temperature, max_tokens
    )


# ── Conversation Memory ───────────────────────────────────────────────

MAX_MEMORY = 10
MEMORY_KEY = "conv_memory"
BIZ_KEY    = "biz_memory"


def get_memory() -> list:
    return session.get(MEMORY_KEY, [])


def add_to_memory(question: str, sql: str, answer: str):
    mem = get_memory()
    mem.append({
        "question" : question,
        "sql"      : sql,
        "answer"   : answer[:500],   # truncate long answers
        "timestamp": dt.datetime.now().isoformat(),
    })
    session[MEMORY_KEY] = mem[-MAX_MEMORY:]
    session.modified = True


def build_memory_context(n: int = 5) -> str:
    mem = get_memory()[-n:]
    if not mem:
        return ""
    lines = ["RECENT CONVERSATION HISTORY (use for follow-up questions):"]
    for i, m in enumerate(mem, 1):
        lines.append(f"{i}. Q: {m['question']}")
        if m.get("sql"):
            lines.append(f"   SQL: {m['sql'][:120]}...")
        lines.append(f"   A: {m['answer'][:200]}")
    return "\n".join(lines)


# ── Business Memory ───────────────────────────────────────────────────

def get_biz_memory() -> dict:
    return session.get(BIZ_KEY, {})


def update_biz_memory(key: str, value: str):
    bm = get_biz_memory()
    bm[key] = value
    session[BIZ_KEY] = bm
    session.modified = True


def extract_and_save_biz_memory(question: str, answer: str, rows: list):
    """Auto-extract entities from results and save to business memory."""
    q_lower = question.lower()
    if not rows:
        return
    first_row = rows[0]
    first_val = list(first_row.values())[0] if first_row else None

    if any(w in q_lower for w in ["top customer", "best customer"]):
        if first_val:
            update_biz_memory("last_top_customer", str(first_val))
    if any(w in q_lower for w in ["top supplier", "best supplier", "concerned supplier"]):
        if first_val:
            update_biz_memory("last_top_supplier", str(first_val))
    if any(w in q_lower for w in ["top product", "best product", "best selling"]):
        if first_val:
            update_biz_memory("last_top_product", str(first_val))


def build_biz_context() -> str:
    bm = get_biz_memory()
    if not bm:
        return ""
    lines = ["BUSINESS MEMORY (use for context-aware follow-ups):"]
    mapping = {
        "last_top_customer": "Last top customer",
        "last_top_supplier": "Last top supplier",
        "last_top_product" : "Last top product",
        "last_forecast"    : "Last forecast scope",
        "last_report"      : "Last report period",
    }
    for k, label in mapping.items():
        if k in bm:
            lines.append(f"- {label}: {bm[k]}")
    return "\n".join(lines)


# ── Schema validation ─────────────────────────────────────────────────

def validate_sql_against_schema(sql: str, schema: dict) -> tuple[bool, str]:
    """
    Check that every real table referenced in the SQL actually exists
    in the schema. CTE names are excluded from validation.
    """
    # Extract CTE names (defined after WITH ... AS) so we don't flag them
    cte_names = set(re.findall(
        r'\b(\w+)\s+AS\s*\(', sql, re.IGNORECASE
    ))

    # Extract table references from FROM and JOIN
    table_refs = re.findall(
        r'\b(?:FROM|JOIN)\s+\[?(\w+)\]?(?:\s+(?:AS\s+)?\w+)?',
        sql, re.IGNORECASE
    )

    schema_tables_upper = {t.upper(): t for t in schema}

    bad_tables = []
    for t in table_refs:
        # Skip CTE names and subquery aliases
        if t.upper() in {c.upper() for c in cte_names}:
            continue
        # Skip common SQL subquery keywords
        if t.upper() in ("SELECT", "WITH", "VALUES"):
            continue
        if t.upper() not in schema_tables_upper:
            bad_tables.append(t)

    if bad_tables:
        return False, f"Tables not found in schema: {', '.join(set(bad_tables))}"

    return True, ""


# ── SQL generation with retry ─────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|ALTER|UPDATE|INSERT|MERGE|CREATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|DENY|SHUTDOWN|KILL|BACKUP|RESTORE)\b", re.IGNORECASE
)

CANNOT_ANSWER = "CANNOT_ANSWER"

_SQL_SYSTEM_TEMPLATE = """You are an expert T-SQL analyst for a Smart Inventory & Sales Analytics Data Warehouse (SQL Server).

Schema:
DimDate(DateKey,FullDate,DayNumber,DayName,MonthNumber,MonthName,QuarterNumber,QuarterName,YearNumber,WeekNumber,MonthYear,IsWeekend)
DimProduct(ProductKey,ProductID,Product,Category,Color,Brand,LastCostPrice)
DimCustomer(CustomerKey,CustomerID,CustomerName,CustomerCategory,BuyingGroup,LocationKey)
DimSupplier(SupplierKey,SupplierID,SupplierName,SupplierCategory,LocationKey)
DimEmployee(EmployeeKey,EmployeeID,FullName,IsSalesperson)
DimLocation(LocationKey,CityID,City,State,Country,Continent)
DimDeliveryMethod(DeliveryMethodKey,DeliveryMethodID,DeliveryMethod)
DimInventoryTransactionType(TransactionTypeKey,TransactionTypeID,TransactionType)
FactSales(SalesKey,InvoiceDateKey,ProductKey,InvoiceID,CustomerKey,EmployeeKey,DeliveryMethodKey,Quantity,UnitPrice,TaxRate,LineTotal,ProfitAmount)
FactPurchases(PurchaseKey,PurchaseDateKey,ExpectedDeliveryDateKey,PurchaseOrderID,ProductKey,SupplierKey,DeliveryMethodKey,TaxRate,QuantityOrdered,UnitCostPrice)
FactInventory(InventoryKey,ProductKey,CurrentStock,ReorderLevel,TargetStockLevel,LastCostPrice)
FactInventoryTransactions(InventoryTransactionKey,DateKey,ProductKey,InvoiceID,PurchaseOrderID,TransactionTypeKey,Quantity)


BUSINESS MEMORY:
{biz_context}

CONVERSATION HISTORY:
{mem_context}

STRICT RULES:
1. Write ONE single T-SQL SELECT (CTEs allowed). No INSERT/UPDATE/DELETE/DROP/EXEC.
2. ONLY use tables and columns listed in the EXACT SCHEMA above.
3. NEVER invent columns like RejectedQty, ReceivedQty, RejectionRate, ReturnRate, or any metric not in the schema.
4. NEVER use GETDATE() — data runs from 2022 to May 2026. Use MAX(YearNumber) from DimDate for "current".
5. Always JOIN Fact tables to Dim tables to get human-readable names.
6. Use TOP N for "top N" questions (default TOP 10 if not specified).
7. DimProduct column is "Product" not "ProductName".
8. DimDate columns: YearNumber, MonthNumber, MonthName (not Year/Month).
9. For supplier/purchase cost questions, calculate cost as: FactPurchases.QuantityOrdered * DimProduct.LastCostPrice * (1 + FactPurchases.TaxRate/100.0). NEVER use FactPurchases.UnitCostPrice for totals — that column contains unreliable/inflated values. DimProduct.LastCostPrice is the trusted cost source.
10. If the requested data does not exist in the schema, return exactly: CANNOT_ANSWER
11. Return ONLY the SQL query. No explanation, no markdown, no code fences.
"""

_ADVISOR_SYSTEM = """You are an expert business advisor for a wholesale distribution company.
Schema:
DimDate(DateKey,FullDate,DayNumber,DayName,MonthNumber,MonthName,QuarterNumber,QuarterName,YearNumber,WeekNumber,MonthYear,IsWeekend)
DimProduct(ProductKey,ProductID,Product,Category,Color,Brand,LastCostPrice)
DimCustomer(CustomerKey,CustomerID,CustomerName,CustomerCategory,BuyingGroup,LocationKey)
DimSupplier(SupplierKey,SupplierID,SupplierName,SupplierCategory,LocationKey)
DimEmployee(EmployeeKey,EmployeeID,FullName,IsSalesperson)
DimLocation(LocationKey,CityID,City,State,Country,Continent)
DimDeliveryMethod(DeliveryMethodKey,DeliveryMethodID,DeliveryMethod)
DimInventoryTransactionType(TransactionTypeKey,TransactionTypeID,TransactionType)
FactSales(SalesKey,InvoiceDateKey,ProductKey,InvoiceID,CustomerKey,EmployeeKey,DeliveryMethodKey,Quantity,UnitPrice,TaxRate,LineTotal,ProfitAmount)
FactPurchases(PurchaseKey,PurchaseDateKey,ExpectedDeliveryDateKey,PurchaseOrderID,ProductKey,SupplierKey,DeliveryMethodKey,TaxRate,QuantityOrdered,UnitCostPrice)
FactInventory(InventoryKey,ProductKey,CurrentStock,ReorderLevel,TargetStockLevel,LastCostPrice)
FactInventoryTransactions(InventoryTransactionKey,DateKey,ProductKey,InvoiceID,PurchaseOrderID,TransactionTypeKey,Quantity)


Given:
1. The user's question
2. The SQL that was run
3. The data result
4. Business memory and conversation history

Your job:
- Answer the question directly with specific numbers from the data.
- Give 1-3 concrete business recommendations.
- Reply in the SAME language as the question (Arabic → Arabic, English → English).
- Be concise (4-8 sentences). Answer first, then bullet recommendations.
- Reference actual names and numbers from the data.
- Do NOT repeat the raw table data.
- Format with clean Markdown: put each bullet/numbered recommendation on its own line, with a blank line between the summary and the list.
"""


def generate_sql_with_retry(question: str, schema: dict) -> tuple[str, str]:
    """
    Generate SQL for a question. Returns (sql, error).
    Validates against schema and retries once on failure.
    """
    schema_text = "\n".join(
        f"  {t}: " + ", ".join(f"{c['name']}({c['type']})" for c in cols)
        for t, cols in schema.items()
    )
    mem_ctx = build_memory_context()
    biz_ctx = build_biz_context()

    system = _SQL_SYSTEM_TEMPLATE.format(
        schema=schema_text,
        mem_context=mem_ctx or "None",
        biz_context=biz_ctx or "None",
    )
    user = f"Question: {question}\n\nSQL:"

    raw = generate_ai_response(system, user, temperature=0.0)

    # Surface gateway/connection failures directly instead of letting them
    # fall through to the SQL-shape checks below (which would misreport
    # them as "Invalid SQL start").
    if raw.startswith(("SBG_API_KEY is not set", "SBG Gateway error",
                        "SBG Gateway returned a non-JSON response",
                        "AI returned an empty response")):
        return "", raw

    # Check for CANNOT_ANSWER
    if CANNOT_ANSWER in raw.upper():
        return CANNOT_ANSWER, raw

    # Clean fences
    sql = re.sub(r"^```[a-zA-Z]*\s*", "", raw.strip())
    sql = re.sub(r"\s*```$", "", sql).strip()

    # Safety check
    if _FORBIDDEN.search(sql):
        return "", "Forbidden SQL operation detected."

    # Multi-statement check
    stmts = [s.strip() for s in sql.split(";") if s.strip()]
    if len(stmts) > 1:
        sql = stmts[0]

    # Must start with SELECT or WITH
    first_word = re.match(r"^\s*(\w+)", sql.upper())
    if not first_word or first_word.group(1) not in ("SELECT", "WITH"):
        return "", f"Invalid SQL start: {sql[:80]}"

    # Schema validation
    valid, err = validate_sql_against_schema(sql, schema)
    if not valid:
        # Retry once with error feedback
        retry_user = (
            f"Question: {question}\n\n"
            f"Previous attempt failed: {err}\n"
            f"Try again using ONLY the exact tables and columns from the schema.\n\n"
            f"SQL:"
        )
        raw2 = generate_ai_response(system, retry_user, temperature=0.0)
        if CANNOT_ANSWER in raw2.upper():
            return CANNOT_ANSWER, raw2
        sql2 = re.sub(r"^```[a-zA-Z]*\s*", "", raw2.strip())
        sql2 = re.sub(r"\s*```$", "", sql2).strip()
        stmts2 = [s.strip() for s in sql2.split(";") if s.strip()]
        sql2 = stmts2[0] if stmts2 else sql2
        valid2, err2 = validate_sql_against_schema(sql2, schema)
        if not valid2:
            return "", (
                f"I cannot answer this question because the required data "
                f"does not exist in the warehouse. ({err2})"
            )
        return sql2, ""

    return sql, ""


# ── Intent detection ──────────────────────────────────────────────────

INTENT_FORECAST = "forecast"
INTENT_REPORT   = "report"
INTENT_MEMORY   = "memory"
INTENT_ADVISORY = "advisory"
INTENT_SQL      = "sql"


# Open-ended strategic questions ("how do I improve sales?") don't map to
# a single SQL query — they need a snapshot of several metrics plus
# reasoning over them. Checked first since these questions often also
# contain time words ("next month") that would otherwise wrongly trigger
# the forecast intent.
_ADVISORY_KEYWORDS = [
    "improve", "increase sales", "increase profit", "boost sales", "boost profit",
    "grow sales", "grow profit", "what should i do", "what do i need to do",
    "how do i improve", "how can i improve", "recommend", "recommendation",
    "advice", "action plan", "strategy",
    "ازاي احسن", "إزاي أحسن", "كيف احسن", "كيف أحسن", "ازاي اطور", "إزاي أطور",
    "نصايح", "نصيحة", "اقترح", "استراتيجية", "خطة عمل",
    "زيادة المبيعات", "زيادة الأرباح", "تحسين المبيعات", "تحسين الأرباح",
]


def detect_intent(question: str) -> str:
    q = question.lower()
    if any(w in q for w in _ADVISORY_KEYWORDS):
        return INTENT_ADVISORY
    if any(w in q for w in ["forecast", "predict", "next month", "future sales", "توقع"]):
        return INTENT_FORECAST
    if any(w in q for w in ["monthly report", "generate report", "send report", "تقرير شهري"]):
        return INTENT_REPORT
    if any(w in q for w in ["previous result", "last answer", "compare with", "that customer",
                              "that supplier", "that product", "show more", "النتيجة السابقة"]):
        return INTENT_MEMORY
    return INTENT_SQL


_ADVISORY_SYSTEM = """You are a senior business strategist for a wholesale distribution company.

You are given a snapshot of recent business data (sales trend, top products,
top customers, top suppliers, low stock, overstock) and an open-ended
question about improving performance (e.g. "how do I improve sales next
month?").

Your job:
- Make 1-2 specific data-backed observations, citing actual names and numbers from the snapshot.
- Give 3-5 concrete, prioritized, actionable recommendations (not generic advice).
- Reply in the SAME language as the question (Arabic → Arabic, English → English).
- Structure: a short 1-2 sentence summary, then a numbered action list.
- Do NOT invent metrics, numbers, or names that aren't in the data provided.
- If the data snapshot is too thin to support a recommendation, say so plainly instead of guessing.
- Format with clean Markdown: put each numbered recommendation on its own line, with a blank line between the summary and the list.
"""


def _advisory_csv(rows: list, n: int = 8) -> str:
    if not rows:
        return "(no data)"
    import csv, io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows[:n])
    return buf.getvalue()


def handle_advisory_intent(question: str) -> dict:
    """
    Answer open-ended strategic questions (e.g. "how do I improve sales?")
    by gathering a snapshot of recent business metrics and asking the model
    to reason over them — instead of forcing the question into a single
    SQL query, which doesn't work for advice-style questions.
    """
    from utils.database import run_query

    def _safe(sql, max_rows=50):
        try:
            return run_query(sql, max_rows=max_rows)
        except Exception:
            return []

    sales_trend = _safe("""
        SELECT TOP 6 d.MonthName + ' ' + CAST(d.YearNumber AS VARCHAR) AS period,
               SUM(f.LineTotal) AS revenue, SUM(f.ProfitAmount) AS profit
        FROM FactSales f JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
        GROUP BY d.YearNumber, d.MonthNumber, d.MonthName
        ORDER BY d.YearNumber DESC, d.MonthNumber DESC
    """)
    top_products = _safe("""
        SELECT TOP 5 dp.Product, SUM(f.LineTotal) AS revenue, SUM(f.ProfitAmount) AS profit
        FROM FactSales f JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
        GROUP BY dp.Product ORDER BY revenue DESC
    """)
    top_customers = _safe("""
        SELECT TOP 5 dc.CustomerName AS customer, SUM(f.LineTotal) AS revenue
        FROM FactSales f JOIN DimCustomer dc ON f.CustomerKey = dc.CustomerKey
        GROUP BY dc.CustomerName ORDER BY revenue DESC
    """)
    top_suppliers = _safe("""
        SELECT TOP 5 ds.SupplierName AS supplier,
               SUM(fp.QuantityOrdered * dp.LastCostPrice * (1 + fp.TaxRate/100.0)) AS spend
        FROM FactPurchases fp JOIN DimSupplier ds ON fp.SupplierKey = ds.SupplierKey
        JOIN DimProduct dp ON fp.ProductKey = dp.ProductKey
        GROUP BY ds.SupplierName ORDER BY spend DESC
    """)
    low_stock = _safe("""
        SELECT TOP 10 dp.Product, fi.CurrentStock, fi.ReorderLevel
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        WHERE fi.CurrentStock <= fi.ReorderLevel
        ORDER BY (fi.ReorderLevel - fi.CurrentStock) DESC
    """)
    overstock = _safe("""
        SELECT TOP 10 dp.Product, fi.CurrentStock, fi.TargetStockLevel
        FROM FactInventory fi JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
        WHERE fi.CurrentStock > fi.TargetStockLevel
        ORDER BY (fi.CurrentStock - fi.TargetStockLevel) DESC
    """)

    mem_ctx = build_memory_context()
    biz_ctx = build_biz_context()

    prompt = (
        f"QUESTION: {question}\n\n"
        f"RECENT SALES TREND (last 6 months, most recent first):\n{_advisory_csv(sales_trend)}\n\n"
        f"TOP PRODUCTS BY REVENUE:\n{_advisory_csv(top_products)}\n\n"
        f"TOP CUSTOMERS BY REVENUE:\n{_advisory_csv(top_customers)}\n\n"
        f"TOP SUPPLIERS BY SPEND:\n{_advisory_csv(top_suppliers)}\n\n"
        f"LOW STOCK ITEMS:\n{_advisory_csv(low_stock)}\n\n"
        f"OVERSTOCK ITEMS:\n{_advisory_csv(overstock)}\n\n"
        f"BUSINESS MEMORY:\n{biz_ctx or 'None'}\n\n"
        f"CONVERSATION HISTORY:\n{mem_ctx or 'None'}\n\n"
        "Write your strategic analysis and action plan:"
    )

    answer = generate_ai_response(_ADVISORY_SYSTEM, prompt, temperature=0.4)
    add_to_memory(question, "", answer)
    return {"answer": answer, "sql": "", "data": [], "intent": INTENT_ADVISORY}


def handle_memory_intent(question: str) -> dict:
    """Answer questions that refer to previous conversation results."""
    mem = get_memory()
    biz = get_biz_memory()

    context = build_memory_context(5) + "\n" + build_biz_context()
    system  = (
        "You are a business assistant. The user is asking a follow-up question "
        "based on previous conversation. Use the memory context to answer directly. "
        "Reply in the same language as the question."
    )
    answer = generate_ai_response(system, f"CONTEXT:\n{context}\n\nQUESTION: {question}")
    return {"answer": answer, "sql": "", "data": [], "intent": INTENT_MEMORY}


# ── Main agent entry point ────────────────────────────────────────────

def run_agent(question: str, schema: dict, engine) -> dict:
    """
    Main agent function. Detects intent, routes to the right tool,
    executes, interprets, saves memory, and logs.
    """
    from utils.database import run_query

    start_time   = time.time()
    cfg_raw      = session.get("config", {})
    provider     = "bedrock_gateway"
    model        = cfg_raw.get("llm_model", SBG_DEFAULT_MODEL)

    intent = detect_intent(question)

    # ── Memory intent ──
    if intent == INTENT_MEMORY:
        result = handle_memory_intent(question)
        exec_time = round(time.time() - start_time, 2)
        _append_log({
            "timestamp"    : dt.datetime.now().isoformat(),
            "question"     : question,
            "intent"       : INTENT_MEMORY,
            "generated_sql": "",
            "rows_returned": 0,
            "provider"     : provider,
            "model"        : model,
            "execution_time": exec_time,
            "answer"       : result["answer"][:300],
        })
        result["execution_time"] = exec_time
        result["provider"]       = provider
        result["model"]          = model
        result["memory_count"]   = len(get_memory())
        return result

    # ── Advisory intent (open-ended strategic questions) ──
    if intent == INTENT_ADVISORY:
        result = handle_advisory_intent(question)
        exec_time = round(time.time() - start_time, 2)
        _append_log({
            "timestamp"    : dt.datetime.now().isoformat(),
            "question"     : question,
            "intent"       : INTENT_ADVISORY,
            "generated_sql": "",
            "rows_returned": 0,
            "provider"     : provider,
            "model"        : model,
            "execution_time": exec_time,
            "answer"       : result["answer"][:300],
        })
        result["execution_time"] = exec_time
        result["provider"]       = provider
        result["model"]          = model
        result["memory_count"]   = len(get_memory())
        return result

    # ── SQL intent ──
    sql, err = generate_sql_with_retry(question, schema)

    if sql == CANNOT_ANSWER:
        answer = (
            "I cannot answer this question because the required data "
            "does not exist in the warehouse."
            if "english" in question.lower() or not any(c > '\u0600' for c in question)
            else "لا يمكنني الإجابة على هذا السؤال لأن البيانات المطلوبة غير موجودة في المستودع."
        )
        _append_log({
            "timestamp"       : dt.datetime.now().isoformat(),
            "question"        : question,
            "intent"          : intent,
            "result"          : "cannot_answer",
            "model_raw_output": (err or "")[:500],
            "provider"        : provider,
            "model"           : model,
            "execution_time"  : round(time.time() - start_time, 2),
        })
        return {
            "answer": answer, "sql": "", "data": [],
            "intent": intent, "provider": provider, "model": model,
            "execution_time": round(time.time() - start_time, 2),
            "memory_count": len(get_memory()),
        }

    if err and not sql:
        return {
            "answer": err, "sql": "", "data": [],
            "intent": intent, "provider": provider, "model": model,
            "execution_time": round(time.time() - start_time, 2),
            "memory_count": len(get_memory()),
        }

    # Execute SQL
    try:
        rows = run_query(sql, max_rows=50)
    except Exception as exc:
        return {
            "answer": f"Query execution failed: {exc}",
            "sql": sql, "data": [],
            "intent": intent, "provider": provider, "model": model,
            "execution_time": round(time.time() - start_time, 2),
            "memory_count": len(get_memory()),
        }

    # AI interpretation
    import csv, io
    if rows:
        buf = io.StringIO()
        w   = csv.DictWriter(buf, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows[:20])
        csv_preview = buf.getvalue()
    else:
        csv_preview = "(no rows returned)"

    mem_ctx = build_memory_context()
    biz_ctx = build_biz_context()

    advisor_prompt = (
        f"QUESTION: {question}\n\n"
        f"SQL:\n{sql}\n\n"
        f"DATA (CSV):\n{csv_preview}\n\n"
        f"BUSINESS MEMORY:\n{biz_ctx or 'None'}\n\n"
        f"CONVERSATION HISTORY:\n{mem_ctx or 'None'}\n\n"
        "Write your business answer and recommendations:"
    )
    answer = generate_ai_response(_ADVISOR_SYSTEM, advisor_prompt, temperature=0.3)

    # Save to memory
    add_to_memory(question, sql, answer)
    extract_and_save_biz_memory(question, answer, rows)

    exec_time = round(time.time() - start_time, 2)

    # Log
    _append_log({
        "timestamp"     : dt.datetime.now().isoformat(),
        "question"      : question,
        "intent"        : intent,
        "generated_sql" : sql,
        "rows_returned" : len(rows),
        "provider"      : provider,
        "model"         : model,
        "execution_time": exec_time,
        "answer"        : answer[:300],
    })

    return {
        "answer"        : answer,
        "sql"           : sql,
        "data"          : rows,
        "intent"        : intent,
        "provider"      : provider,
        "model"         : model,
        "execution_time": exec_time,
        "rows_returned" : len(rows),
        "memory_count"  : len(get_memory()),
    }