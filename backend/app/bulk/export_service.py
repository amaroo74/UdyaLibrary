"""
Export services for CSV, Excel (XLSX), and printable PDF catalogues.
Strictly exports approved catalogue fields:
Serial Number, Stock Number, Title, Author, Publisher, Category, Subcategory, Price (₹).
"""

import csv
import io
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from ..models import Book

EXPORT_COLUMNS = [
    "Serial Number",
    "Stock Number",
    "Book Title",
    "Author",
    "Publisher",
    "Category",
    "Subcategory",
    "Price (INR)",
]


def export_books_csv(books: list[Book]) -> bytes:
    """Generate a clean UTF-8 encoded CSV string with BOM for Excel compatibility."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(EXPORT_COLUMNS)

    for b in books:
        price_val = f"{float(b.price):.2f}" if b.price is not None else ""
        writer.writerow([
            b.serial_number,
            b.stock_number,
            b.title,
            b.author or "",
            b.publisher or "",
            b.category or "",
            b.subcategory or "",
            price_val,
        ])

    return output.getvalue().encode("utf-8-sig")


def export_books_xlsx(books: list[Book]) -> bytes:
    """Generate a professionally styled Excel XLSX workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Catalogue"

    # Styling definitions
    header_fill = PatternFill(start_color="234F3C", end_color="234F3C", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style="thin", color="E0E0E0"),
        right=Side(style="thin", color="E0E0E0"),
        top=Side(style="thin", color="E0E0E0"),
        bottom=Side(style="thin", color="E0E0E0"),
    )

    # Title block
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = "UDAYA VAYANASALA — BOOK CATALOGUE DATASET"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="1E3C2F")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Metadata row
    ws.merge_cells("A2:H2")
    sub_cell = ws["A2"]
    sub_cell.value = f"Exported on: {datetime.now().strftime('%d-%m-%Y %H:%M')} | Total Copies: {len(books)}"
    sub_cell.font = Font(name="Calibri", size=9, italic=True, color="666666")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")

    # Header Row
    ws.append([])  # Blank row 3
    ws.append(EXPORT_COLUMNS)  # Row 4
    header_row = ws[4]
    for cell in header_row:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Data Rows
    for b in books:
        price_val = float(b.price) if b.price is not None else None
        ws.append([
            b.serial_number,
            b.stock_number,
            b.title,
            b.author or "",
            b.publisher or "",
            b.category or "",
            b.subcategory or "",
            price_val,
        ])

    # Format data cells
    for row in ws.iter_rows(min_row=5, max_row=ws.max_row, min_col=1, max_col=8):
        for cell in row:
            cell.font = data_font
            cell.border = thin_border
            if cell.column == 8 and cell.value is not None:
                cell.number_format = "₹#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif cell.column in (1, 2):
                cell.alignment = Alignment(horizontal="center")

    # Column widths
    col_widths = [16, 16, 36, 24, 20, 16, 16, 14]
    for i, w in enumerate(col_widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(i)
        ws.column_dimensions[col_letter].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_books_pdf(books: list[Book]) -> bytes:
    """Generate a clean, printable PDF catalogue report using ReportLab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=colors.HexColor("#234F3C"),
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=14,
    )
    cell_style = ParagraphStyle(
        "CellText",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    header_style = ParagraphStyle(
        "HeaderCellText",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    elements = [
        Paragraph("UDAYA VAYANASALA — BOOK CATALOGUE", title_style),
        Paragraph(
            f"Erattapuzha, Blangad, Chavakkad · Generated on {datetime.now().strftime('%d-%m-%Y %H:%M')} · Total Copies: {len(books)}",
            meta_style,
        ),
    ]

    table_data = [[
        Paragraph(col, header_style) for col in EXPORT_COLUMNS
    ]]

    for b in books:
        price_str = f"₹{float(b.price):.2f}" if b.price is not None else "—"
        table_data.append([
            Paragraph(b.serial_number, cell_style),
            Paragraph(b.stock_number, cell_style),
            Paragraph(b.title, cell_style),
            Paragraph(b.author or "—", cell_style),
            Paragraph(b.publisher or "—", cell_style),
            Paragraph(b.category or "—", cell_style),
            Paragraph(b.subcategory or "—", cell_style),
            Paragraph(price_str, cell_style),
        ])

    col_widths = [1.1 * inch, 1.1 * inch, 2.7 * inch, 1.8 * inch, 1.4 * inch, 1.1 * inch, 1.1 * inch, 0.9 * inch]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#234F3C")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAF9")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E7E2")),
    ]))
    elements.append(t)

    doc.build(elements)
    return buf.getvalue()
