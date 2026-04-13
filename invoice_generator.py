"""
invoice_generator.py
Generates a professional PDF invoice for a single customer using ReportLab.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Content width: A4 (595.28 pt) minus 20mm left and 20mm right margins
_CONTENT_W = A4[0] - 40 * mm  # ≈ 481.9 pt

from excel_reader import CustomerInvoiceData


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
DARK_BLUE  = colors.HexColor("#1A3557")
MID_BLUE   = colors.HexColor("#2F6DAB")
LIGHT_BLUE = colors.HexColor("#D6E4F2")
ACCENT     = colors.HexColor("#F0A500")
LIGHT_GREY = colors.HexColor("#F5F5F5")
MID_GREY   = colors.HexColor("#CCCCCC")
DARK_GREY  = colors.HexColor("#444444")
WHITE      = colors.white
BLACK      = colors.black


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_invoice(
    customer: CustomerInvoiceData,
    invoice_number: str,
    output_dir: str | Path,
    company: dict,
    tax_rate: float = 0.20,
    currency: str = "£",
) -> Path:
    """
    Build a PDF invoice and save it to output_dir.

    Args:
        customer:       CustomerInvoiceData with order lines.
        invoice_number: Unique invoice reference (e.g. 'INV-0042').
        output_dir:     Directory to write the PDF into.
        company:        Dict with keys: name, address, city, postcode, country,
                        email, phone, vat.
        tax_rate:       Decimal tax rate (default 0.20 for 20% VAT).
        currency:       Currency symbol prefix (default '£').

    Returns:
        Path to the generated PDF file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(customer.customer_name)
    pdf_path = output_dir / f"{invoice_number}_{safe_name}.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
    )

    story = _build_story(customer, invoice_number, company, tax_rate, currency)
    doc.build(story, onFirstPage=_page_border, onLaterPages=_page_border)

    return pdf_path


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().replace(" ", "_")


def _build_story(
    customer: CustomerInvoiceData,
    invoice_number: str,
    company: dict,
    tax_rate: float,
    currency: str,
) -> list:
    styles = getSampleStyleSheet()
    story = []

    # ---- Header row: company brand left, invoice meta right ----------------
    story.append(_header_table(invoice_number, company, currency, styles))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=2, color=DARK_BLUE))
    story.append(Spacer(1, 6 * mm))

    # ---- Bill To / Invoice Details side-by-side ----------------------------
    story.append(_bill_to_table(customer, invoice_number, company, styles))
    story.append(Spacer(1, 8 * mm))

    # ---- Line items table --------------------------------------------------
    story.append(_items_table(customer, currency, styles))
    story.append(Spacer(1, 6 * mm))

    # ---- Totals block (right-aligned) -------------------------------------
    subtotal = customer.subtotal
    tax      = round(subtotal * tax_rate, 2)
    total    = round(subtotal + tax, 2)
    story.append(_totals_table(subtotal, tax, total, tax_rate, currency, styles))
    story.append(Spacer(1, 10 * mm))

    # ---- Footer note -------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GREY))
    story.append(Spacer(1, 3 * mm))
    story.append(_footer(company, styles))

    return story


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _header_table(invoice_number: str, company: dict, currency: str, styles) -> Table:
    company_style = ParagraphStyle(
        "CompanyName",
        fontSize=20,
        textColor=DARK_BLUE,
        fontName="Helvetica-Bold",
        leading=24,
    )
    sub_style = ParagraphStyle(
        "CompanySub",
        fontSize=8,
        textColor=DARK_GREY,
        fontName="Helvetica",
        leading=11,
    )
    inv_label_style = ParagraphStyle(
        "InvLabel",
        fontSize=28,
        textColor=DARK_BLUE,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
        leading=32,
    )
    inv_num_style = ParagraphStyle(
        "InvNum",
        fontSize=11,
        textColor=MID_BLUE,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    inv_date_style = ParagraphStyle(
        "InvDate",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica",
        alignment=TA_RIGHT,
    )

    left = [
        Paragraph(company.get("name", "Your Company"), company_style),
        Spacer(1, 2 * mm),
        Paragraph(company.get("address", ""), sub_style),
        Paragraph(
            f"{company.get('city', '')}  {company.get('postcode', '')}",
            sub_style,
        ),
        Paragraph(company.get("country", ""), sub_style),
        Spacer(1, 2 * mm),
        Paragraph(f"Email: {company.get('email', '')}", sub_style),
        Paragraph(f"Phone: {company.get('phone', '')}", sub_style),
        Paragraph(f"VAT: {company.get('vat', '')}", sub_style),
    ]

    right = [
        Paragraph("INVOICE", inv_label_style),
        Paragraph(invoice_number, inv_num_style),
        Spacer(1, 3 * mm),
        Paragraph(f"Date: {date.today().strftime('%d %B %Y')}", inv_date_style),
        Paragraph(f"Due: {date.today().strftime('%d %B %Y')}", inv_date_style),
    ]

    t = Table([[left, right]], colWidths=[_CONTENT_W * 0.55, _CONTENT_W * 0.45])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _bill_to_table(
    customer: CustomerInvoiceData,
    invoice_number: str,
    company: dict,
    styles,
) -> Table:
    label_style = ParagraphStyle(
        "BillLabel",
        fontSize=8,
        textColor=WHITE,
        fontName="Helvetica-Bold",
        leading=10,
    )
    value_style = ParagraphStyle(
        "BillValue",
        fontSize=10,
        textColor=DARK_GREY,
        fontName="Helvetica",
        leading=14,
    )
    name_style = ParagraphStyle(
        "BillName",
        fontSize=12,
        textColor=DARK_BLUE,
        fontName="Helvetica-Bold",
        leading=15,
    )

    bill_cell = [
        Paragraph("BILL TO", label_style),
        Spacer(1, 3 * mm),
        Paragraph(customer.customer_name, name_style),
        Paragraph(customer.email, value_style),
    ]

    info_label = ParagraphStyle(
        "InfoLabel",
        fontSize=8,
        textColor=DARK_GREY,
        fontName="Helvetica-Bold",
    )
    info_val = ParagraphStyle(
        "InfoVal",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica",
    )
    # Collect unique order numbers
    order_nums = sorted({line.order_number for line in customer.order_lines})
    info_cell = [
        Paragraph("INVOICE REFERENCE", info_label),
        Paragraph(invoice_number, info_val),
        Spacer(1, 2 * mm),
        Paragraph("ORDER NUMBERS", info_label),
        Paragraph(", ".join(order_nums), info_val),
        Spacer(1, 2 * mm),
        Paragraph("TOTAL ORDERS", info_label),
        Paragraph(str(len(customer.order_lines)), info_val),
    ]

    t = Table([[bill_cell, info_cell]], colWidths=[_CONTENT_W * 0.60, _CONTENT_W * 0.40])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), DARK_BLUE),
        ("BACKGROUND", (1, 0), (1, 0), LIGHT_BLUE),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def _items_table(customer: CustomerInvoiceData, currency: str, styles) -> Table:
    header_style = ParagraphStyle(
        "ItemHeader",
        fontSize=8,
        textColor=WHITE,
        fontName="Helvetica-Bold",
        leading=10,
    )
    cell_style = ParagraphStyle(
        "ItemCell",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica",
        leading=12,
    )
    num_style = ParagraphStyle(
        "ItemNum",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica",
        alignment=TA_RIGHT,
        leading=12,
    )

    headers = [
        Paragraph("DATE",        header_style),
        Paragraph("ORDER #",     header_style),
        Paragraph("DESCRIPTION", header_style),
        Paragraph("QTY",         header_style),
        Paragraph("UNIT PRICE",  header_style),
        Paragraph("TOTAL",       header_style),
    ]

    rows = [headers]
    for i, line in enumerate(customer.order_lines):
        bg = LIGHT_GREY if i % 2 == 0 else WHITE
        rows.append([
            Paragraph(line.order_date, cell_style),
            Paragraph(line.order_number, cell_style),
            Paragraph(line.description, cell_style),
            Paragraph(f"{line.quantity:g}", num_style),
            Paragraph(f"{currency}{line.unit_price:,.2f}", num_style),
            Paragraph(f"{currency}{line.line_total:,.2f}", num_style),
        ])

    col_widths = [
        _CONTENT_W * 0.15,  # Date
        _CONTENT_W * 0.14,  # Order #
        _CONTENT_W * 0.36,  # Description
        _CONTENT_W * 0.08,  # Qty
        _CONTENT_W * 0.13,  # Unit Price
        _CONTENT_W * 0.14,  # Total
    ]

    t = Table(rows, colWidths=col_widths, repeatRows=1)

    row_count = len(rows)
    style_cmds = [
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        # Data rows
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TOPPADDING",    (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        # Alternating rows
        *[
            ("BACKGROUND", (0, i), (-1, i), LIGHT_GREY if i % 2 == 0 else WHITE)
            for i in range(1, row_count)
        ],
        # Bottom border on each row
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, MID_GREY),
        # Outer border
        ("BOX",    (0, 0), (-1, -1), 1, DARK_BLUE),
    ]

    t.setStyle(TableStyle(style_cmds))
    return t


def _totals_table(
    subtotal: float,
    tax: float,
    total: float,
    tax_rate: float,
    currency: str,
    styles,
) -> Table:
    lbl_style = ParagraphStyle(
        "TotalLbl",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica",
        alignment=TA_RIGHT,
    )
    val_style = ParagraphStyle(
        "TotalVal",
        fontSize=9,
        textColor=DARK_GREY,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    grand_lbl = ParagraphStyle(
        "GrandLbl",
        fontSize=11,
        textColor=WHITE,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )
    grand_val = ParagraphStyle(
        "GrandVal",
        fontSize=11,
        textColor=WHITE,
        fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )

    tax_pct = int(tax_rate * 100)
    data = [
        [Paragraph("Subtotal", lbl_style),             Paragraph(f"{currency}{subtotal:,.2f}", val_style)],
        [Paragraph(f"Tax ({tax_pct}% VAT)", lbl_style), Paragraph(f"{currency}{tax:,.2f}", val_style)],
        [Paragraph("TOTAL DUE", grand_lbl),             Paragraph(f"{currency}{total:,.2f}", grand_val)],
    ]

    # Right-align the totals block by wrapping in an outer table
    inner = Table(data, colWidths=[120, 80])
    inner.setStyle(TableStyle([
        ("BACKGROUND",    (0, 2), (-1, 2), DARK_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("LINEABOVE",     (0, 1), (-1, 1), 0.5, MID_GREY),
        ("LINEABOVE",     (0, 2), (-1, 2), 1.5, DARK_BLUE),
        ("BOX",           (0, 0), (-1, -1), 1, DARK_BLUE),
    ]))

    wrapper = Table([[Spacer(1, 1), inner]], colWidths=[_CONTENT_W - 200, 200])
    wrapper.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return wrapper


def _footer(company: dict, styles) -> Paragraph:
    footer_style = ParagraphStyle(
        "Footer",
        fontSize=8,
        textColor=DARK_GREY,
        fontName="Helvetica",
        alignment=TA_CENTER,
        leading=12,
    )
    text = (
        f"<b>{company.get('name', '')}</b> &nbsp;|&nbsp; "
        f"{company.get('address', '')}, {company.get('city', '')}, "
        f"{company.get('postcode', '')}, {company.get('country', '')} &nbsp;|&nbsp; "
        f"VAT: {company.get('vat', '')} &nbsp;|&nbsp; "
        f"{company.get('email', '')}"
    )
    return Paragraph(text, footer_style)


# ---------------------------------------------------------------------------
# Page decorators
# ---------------------------------------------------------------------------

def _page_border(canvas, doc):
    """Draw a thin coloured border around every page."""
    canvas.saveState()
    canvas.setStrokeColor(DARK_BLUE)
    canvas.setLineWidth(1.5)
    canvas.rect(
        8 * mm,
        8 * mm,
        A4[0] - 16 * mm,
        A4[1] - 16 * mm,
    )
    # Accent stripe at top
    canvas.setFillColor(ACCENT)
    canvas.setStrokeColor(ACCENT)
    canvas.rect(8 * mm, A4[1] - 11 * mm, A4[0] - 16 * mm, 3 * mm, fill=1, stroke=0)
    canvas.restoreState()
