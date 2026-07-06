"""
services/export_service.py
----------------------------
Shared helpers for turning tabular data (a "properties assigned" list, the
audit ledger, etc.) into a downloadable CSV or PDF file. Used by
services/user_service.py, services/outsider_service.py, and
services/audit_service.py so every exporter in the app escapes/formats data
exactly the same way instead of re-implementing it three separate times.
"""

import csv
import io
from typing import Iterable, Optional, Sequence
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ---------------------------------------------------------------------------
# CSV / "Formula Injection" protection
# ---------------------------------------------------------------------------
# Several columns across our exports (asset names, user/outsider names,
# audit `details`, etc.) contain free text that ultimately originated from
# something someone typed elsewhere in the app. If any of that text happens
# to start with '=', '+', '-', or '@', Microsoft Excel / Google Sheets /
# LibreOffice will interpret the ENTIRE cell as a FORMULA the instant
# someone opens the exported CSV -- e.g. a name of "=HYPERLINK(...)" could
# silently execute a spreadsheet formula on whoever opens the file. We
# defend against this the standard, industry-recommended way: prefix any
# such value with a single quote (') before writing it to the CSV, which
# makes every spreadsheet program render it as plain literal text instead.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def csv_safe_cell(value) -> str:
    """Neutralizes formula-injection payloads before they reach a CSV cell."""
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + text
    return text


def build_csv_bytes(headers: Sequence[str], rows: Iterable[Sequence]) -> bytes:
    """
    Builds a complete CSV file in memory and returns it as UTF-8 bytes.

    This is appropriate for every export in this module EXCEPT the audit
    ledger's CSV export, which stays row-by-row STREAMED instead (see
    services/audit_service.export_audit_logs_csv) because that ledger is an
    append-only log that can grow without bound over the system's lifetime.
    Every other export here (one user's/outsider's assigned items, or a
    full directory's worth of them) is a bounded, "give me everything
    right now" dataset small enough to build in memory in one shot.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_safe_cell(cell) for cell in row])
    return output.getvalue().encode("utf-8")


def build_pdf_bytes(title: str, subtitle: Optional[str], headers: Sequence[str], rows: Iterable[Sequence]) -> bytes:
    """
    Renders the same tabular data as a simple, print-friendly PDF using
    reportlab's Platypus layout engine: one title, an optional subtitle
    line, then a single table with a repeating header row on every page.

    `title`/`subtitle` are passed through `Paragraph`, which interprets a
    small subset of HTML-like markup -- so we XML-escape them first in case
    either one ever contains user-typed text with a stray '<' or '&' in it
    (a name, an email, etc.), which would otherwise raise a parse error.
    Table CELLS are plain strings (not wrapped in Paragraph), so reportlab
    draws them literally and no such escaping is needed for `rows`.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.6 * inch, bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements = [Paragraph(xml_escape(title), styles["Title"])]
    if subtitle:
        elements.append(Paragraph(xml_escape(subtitle), styles["Normal"]))
    elements.append(Spacer(1, 0.25 * inch))

    table_data = [list(headers)] + [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()
