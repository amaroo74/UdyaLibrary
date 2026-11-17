"""
Import service for CSV and Excel (XLSX) files with column mapping,
validation, duplicate detection, and row-level error reporting.
"""

import csv
import io
import re
from decimal import Decimal
from typing import Any
from uuid import uuid4
import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Book
from ..services import enqueue_change, log_action

HEADER_MAP = {
    "stock_number": ["stock number", "stock no", "stock_number", "stockno", "stock"],
    "title": ["book title", "title", "book_title", "book"],
    "author": ["author", "author name", "author_name", "writer"],
    "publisher": ["publisher", "publication", "press"],
    "category": ["category", "genre"],
    "subcategory": ["subcategory", "sub category", "sub_category"],
    "price": ["price", "price (inr)", "price (₹)", "cost", "amount"],
}


def clean_header(header: str) -> str:
    return re.sub(r"[_\s]+", " ", str(header).strip().lower())


def map_headers(raw_headers: list[str]) -> dict[str, int]:
    """Map raw table headers to internal canonical field names."""
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(raw_headers):
        cleaned = clean_header(raw)
        for canon, aliases in HEADER_MAP.items():
            if cleaned in aliases and canon not in mapping:
                mapping[canon] = idx
                break
    return mapping


def parse_price(val: Any) -> Decimal | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Strip currency symbols and commas
    cleaned = re.sub(r"[^\d.]", "", s)
    try:
        p = Decimal(cleaned)
        return p if p >= 0 else None
    except Exception:
        return None


def process_import_rows(
    rows: list[list[Any]],
    headers: list[str],
    db: Session,
    actor: str = "system",
    actor_role: str = "librarian",
    device_id: str = "device-local",
) -> dict[str, Any]:
    """
    Validate and process rows from CSV or XLSX.
    Returns { "imported_count": int, "errors": list[dict], "books": list[Book] }
    """
    mapping = map_headers(headers)
    if "stock_number" not in mapping or "title" not in mapping:
        return {
            "success": False,
            "imported_count": 0,
            "errors": [
                {
                    "row": 1,
                    "error": "Missing required header columns. File must contain 'Stock Number' and 'Book Title'.",
                }
            ],
        }

    # Fetch existing stock numbers in DB to check collisions
    existing_stocks = set(db.scalars(select(Book.stock_number)).all())
    batch_stocks = set()

    imported_books: list[Book] = []
    errors: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows, start=2):
        if not any(row):  # Skip completely empty rows
            continue

        def get_val(canon: str) -> str:
            col_idx = mapping.get(canon)
            if col_idx is not None and col_idx < len(row):
                v = row[col_idx]
                return str(v).strip() if v is not None else ""
            return ""

        stock_no = get_val("stock_number")
        title = get_val("title")
        author = get_val("author") or None
        publisher = get_val("publisher") or None
        category = get_val("category") or None
        subcategory = get_val("subcategory") or None
        price_raw = mapping.get("price")
        price_val = parse_price(row[price_raw]) if price_raw is not None and price_raw < len(row) else None

        if not stock_no:
            errors.append({"row": row_idx, "error": "Stock number cannot be blank."})
            continue
        if not title:
            errors.append({"row": row_idx, "error": "Book title cannot be blank."})
            continue

        if stock_no in existing_stocks:
            errors.append({
                "row": row_idx,
                "error": f"Stock number '{stock_no}' is already registered in the library.",
            })
            continue

        if stock_no in batch_stocks:
            errors.append({
                "row": row_idx,
                "error": f"Stock number '{stock_no}' appears multiple times in this import file.",
            })
            continue

        batch_stocks.add(stock_no)
        book = Book(
            serial_number=f"PENDING-{uuid4().hex}",
            device_id=device_id,
            stock_number=stock_no,
            title=title,
            author=author,
            publisher=publisher,
            category=category,
            subcategory=subcategory,
            price=price_val,
        )
        db.add(book)
        db.flush()
        book.serial_number = f"UDY-{book.id:06d}"
        enqueue_change(
            db,
            operation="CREATE",
            entity_type="book",
            entity_id=book.id,
            payload={
                "serial_number": book.serial_number,
                "stock_number": book.stock_number,
                "title": book.title,
                "author": book.author,
                "publisher": book.publisher,
                "category": book.category,
                "subcategory": book.subcategory,
                "price": book.price,
                "device_id": book.device_id,
            },
            device_id=device_id,
        )
        imported_books.append(book)
        existing_stocks.add(stock_no)

    if imported_books:
        db.commit()
        log_action(
            db,
            "bulk_import_completed",
            None,
            {"count": len(imported_books), "error_count": len(errors)},
            actor=actor,
            actor_role=actor_role,
            entity_type="bulk",
        )
        db.commit()

    return {
        "success": True,
        "imported_count": len(imported_books),
        "error_count": len(errors),
        "errors": errors,
    }


def import_books_csv(
    file_bytes: bytes,
    db: Session,
    actor: str = "system",
    actor_role: str = "librarian",
    device_id: str = "device-local",
) -> dict[str, Any]:
    """Parse and import books from a CSV file."""
    # Try UTF-8 (and strip BOM if present)
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"success": False, "imported_count": 0, "errors": [{"row": 0, "error": "CSV file is empty."}]}

    headers = rows[0]
    data_rows = rows[1:]
    return process_import_rows(data_rows, headers, db, actor, actor_role, device_id)


def import_books_xlsx(
    file_bytes: bytes,
    db: Session,
    actor: str = "system",
    actor_role: str = "librarian",
    device_id: str = "device-local",
) -> dict[str, Any]:
    """Parse and import books from an Excel XLSX file."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as exc:
        return {"success": False, "imported_count": 0, "errors": [{"row": 0, "error": f"Invalid Excel file: {exc}"}]}

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"success": False, "imported_count": 0, "errors": [{"row": 0, "error": "Excel file is empty."}]}

    # Find the header row (skip top title blocks if present)
    header_idx = 0
    for idx, r in enumerate(rows[:5]):
        str_cells = [clean_header(c) for c in r if c is not None]
        if any(h in str_cells for h in ["stock number", "stock no", "title", "book title"]):
            header_idx = idx
            break

    headers = [str(c) if c is not None else "" for c in rows[header_idx]]
    data_rows = [list(r) for r in rows[header_idx + 1:]]
    return process_import_rows(data_rows, headers, db, actor, actor_role, device_id)
