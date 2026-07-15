"""
utils/report_pdf.py
--------------------
Builds the Monthly Executive Report as a PDF.

Shared by:
  - utils/scheduler.py   (automated monthly email)
  - api/routes.py        (manual "Send Email" button)

Uses reportlab — pure Python, no external binaries (no wkhtmltopdf /
GTK needed), so it works the same on Windows/Mac/Linux.
"""

from __future__ import annotations

import io
import re
import unicodedata
import datetime as dt

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    ListFlowable, ListItem, HRFlowable,
)

_STYLES = getSampleStyleSheet()

_TITLE_STYLE = ParagraphStyle(
    "ReportTitle", parent=_STYLES["Title"], fontSize=18,
    textColor=colors.HexColor("#6D6256"), spaceAfter=4,
)
_SUB_STYLE = ParagraphStyle(
    "ReportSub", parent=_STYLES["Normal"], fontSize=9,
    textColor=colors.HexColor("#777777"), spaceAfter=14,
)
_KPI_STYLE = ParagraphStyle(
    "Kpi", parent=_STYLES["Normal"], fontSize=12, spaceAfter=14,
)
_H2_STYLE = ParagraphStyle(
    "H2", parent=_STYLES["Heading2"], fontSize=13,
    textColor=colors.HexColor("#6D6256"), spaceBefore=16, spaceAfter=8,
)
_BODY_STYLE = ParagraphStyle(
    "Body", parent=_STYLES["Normal"], fontSize=10.5, leading=15, spaceAfter=6,
)
_BULLET_STYLE = ParagraphStyle("Bullet", parent=_BODY_STYLE)


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


def _clean_unicode(text: str) -> str:
    """
    Guarantee every character can actually be drawn by ReportLab's default
    font (Helvetica, which uses WinAnsiEncoding / cp1252). Any character
    NOT representable in cp1252 — non-breaking hyphen (U+2011), Arabic,
    emoji, etc. — silently renders as a solid black box (.notdef glyph)
    instead of raising an error, which is why it's easy to ship without
    noticing.

    Strategy:
      1. If a character IS representable in cp1252 (this already covers
         en dash –, em dash —, smart quotes, ellipsis, bullet • — these
         render fine today and are left untouched).
      2. Otherwise, map known dash/hyphen look-alikes to a plain "-".
      3. Otherwise, try an ASCII transliteration (e.g. accented Latin
         letters fall back to their base letter).
      4. Otherwise, drop the character rather than show a black box.
    """
    if not text:
        return text

    dash_lookalikes = {
        "\u2010", "\u2011", "\u2012", "\u2015", "\u2043", "\u2212", "\ufe63", "\uff0d",
    }
    symbol_fallbacks = {
        "\u2248": "~",   # approximately equal to (≈)
        "\u2192": "->",  # rightwards arrow
        "\u2190": "<-",  # leftwards arrow
        "\u00d7": "x",   # multiplication sign
        "\u00f7": "/",   # division sign
    }

    out = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass

        if ch in dash_lookalikes:
            out.append("-")
            continue
        if ch in symbol_fallbacks:
            out.append(symbol_fallbacks[ch])
            continue
        if ch == "\u00ad":  # soft hyphen — invisible, just drop it
            continue

        fallback = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
        out.append(fallback)  # may be "" if there's no reasonable ASCII equivalent

    return "".join(out)


def _bold_inline(text: str) -> str:
    """**bold** → ReportLab's <b> tag (Paragraph supports this small XML subset)."""
    text = _clean_unicode(text)
    # Escape any stray angle brackets first so the model's text can't
    # break ReportLab's mini-XML parser.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _narrative_flowables(narrative: str) -> list:
    """Turn the AI narrative (Markdown-ish text) into ReportLab flowables:
    paragraphs for prose, numbered/bulleted ListFlowables for list items."""
    if not narrative:
        return [Paragraph("No summary available.", _BODY_STYLE)]

    text = narrative.strip()
    # Force a break before inline list markers that run on the same line
    # as the previous sentence (some models skip real newlines).
    text = re.sub(r"([.:!?])\s+-\s+(?=\S)", r"\1\n- ", text)
    text = re.sub(r"([.:!?])\s+(\d+)\.\s+(?=\S)", r"\1\n\2. ", text)

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    flow: list = []
    buffer_items: list = []
    buffer_type = None  # "1" (numbered) | "bullet" | None

    def flush():
        nonlocal buffer_items, buffer_type
        if buffer_items:
            flow.append(ListFlowable(
                [ListItem(Paragraph(_bold_inline(t), _BULLET_STYLE), leftIndent=14)
                 for t in buffer_items],
                bulletType=buffer_type or "bullet",
            ))
            buffer_items = []
            buffer_type = None

    for line in lines:
        num_match    = re.match(r"^(\d+)\.\s+(.*)", line)
        bullet_match = re.match(r"^[-*]\s+(.*)", line)
        if num_match:
            if buffer_type not in (None, "1"):
                flush()
            buffer_type = "1"
            buffer_items.append(num_match.group(2))
        elif bullet_match:
            if buffer_type not in (None, "bullet"):
                flush()
            buffer_type = "bullet"
            buffer_items.append(bullet_match.group(1))
        else:
            flush()
            flow.append(Paragraph(_bold_inline(line), _BODY_STYLE))

    flush()
    return flow


def _data_table(rows: list, max_rows: int = 8):
    if not rows:
        return None
    keys = list(rows[0].keys())
    body = [
        [_clean_unicode(str(r.get(k, "") if r.get(k) is not None else "—")) for k in keys]
        for r in rows[:max_rows]
    ]
    data = [keys] + body

    table = Table(data, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a56db")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))
    return table


def build_report_pdf(period: str, total_sales, total_profit, margin: str,
                      narrative: str,
                      top_products: list, top_customers: list,
                      top_suppliers: list, low_stock: list,
                      overstock: list) -> bytes:
    """Build the Monthly Executive Report as a PDF and return its bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=f"Smart Inventory — {period}",
    )

    story = [
        Paragraph(f"Smart Inventory — {period}", _TITLE_STYLE),
        Paragraph(
            f"Generated by Smart Inventory Copilot on {dt.date.today().strftime('%d %b %Y')}",
            _SUB_STYLE,
        ),
        HRFlowable(width="100%", color=colors.HexColor("#e2e8f0")),
        Spacer(1, 10),
        Paragraph(
            f"<b>Sales:</b> {_fmt(total_sales)} &nbsp;|&nbsp; "
            f"<b>Profit:</b> {_fmt(total_profit)} &nbsp;|&nbsp; "
            f"<b>Margin:</b> {margin}",
            _KPI_STYLE,
        ),
        Paragraph("Key Insights & Recommendations", _H2_STYLE),
    ]
    story.extend(_narrative_flowables(narrative))

    for title, rows in [
        ("Top Products", top_products),
        ("Top Customers", top_customers),
        ("Top Suppliers", top_suppliers),
        ("Low Stock Products", low_stock),
        ("Overstock Alerts", overstock),
    ]:
        story.append(Paragraph(title, _H2_STYLE))
        table = _data_table(rows)
        story.append(table if table is not None else Paragraph("No data available.", _BODY_STYLE))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#e2e8f0")))
    story.append(Paragraph(
        "This report was generated automatically by Smart Inventory Copilot.", _SUB_STYLE,
    ))

    doc.build(story)
    return buf.getvalue()