from datetime import datetime
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Book, User
from ..schemas import BookCreate, BookRead
from ..services import book_to_dict, log_action, enqueue_change
from ..auth.dependencies import (
    get_authenticated_device_id,
    require_admin,
    require_any_authenticated,
)
from ..bulk.export_service import export_books_csv, export_books_pdf, export_books_xlsx
from ..bulk.import_service import import_books_csv, import_books_xlsx
from ..bulk.backup_service import create_database_backup_bytes, restore_database_from_bytes

router = APIRouter(prefix="/api/bulk", tags=["bulk"])


@router.get("/export/csv")
def download_csv(
    q: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    stmt = select(Book).where(Book.is_deleted.is_(False))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Book.serial_number.ilike(pattern),
            Book.stock_number.ilike(pattern),
            Book.title.ilike(pattern),
            Book.author.ilike(pattern),
        ))
    if category:
        stmt = stmt.where(Book.category == category)
    if subcategory:
        stmt = stmt.where(Book.subcategory == subcategory)

    books = db.scalars(stmt.order_by(Book.id.asc())).all()
    csv_bytes = export_books_csv(books)

    filename = f"udaya_catalogue_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/xlsx")
def download_xlsx(
    q: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    stmt = select(Book).where(Book.is_deleted.is_(False))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Book.serial_number.ilike(pattern),
            Book.stock_number.ilike(pattern),
            Book.title.ilike(pattern),
            Book.author.ilike(pattern),
        ))
    if category:
        stmt = stmt.where(Book.category == category)
    if subcategory:
        stmt = stmt.where(Book.subcategory == subcategory)

    books = db.scalars(stmt.order_by(Book.id.asc())).all()
    xlsx_bytes = export_books_xlsx(books)

    filename = f"udaya_catalogue_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/pdf")
def download_pdf(
    q: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    stmt = select(Book).where(Book.is_deleted.is_(False))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Book.serial_number.ilike(pattern),
            Book.stock_number.ilike(pattern),
            Book.title.ilike(pattern),
            Book.author.ilike(pattern),
        ))
    if category:
        stmt = stmt.where(Book.category == category)
    if subcategory:
        stmt = stmt.where(Book.subcategory == subcategory)

    books = db.scalars(stmt.order_by(Book.id.asc())).all()
    pdf_bytes = export_books_pdf(books)

    filename = f"udaya_catalogue_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    """
    Import books from uploaded CSV or Excel XLSX file.
    Validates required fields and reports row-level errors.
    """
    actor = current_user.email
    actor_role = current_user.role

    contents = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".csv"):
        result = import_books_csv(
            contents, db, actor=actor, actor_role=actor_role, device_id=device_id
        )
    elif filename.endswith((".xlsx", ".xls")):
        result = import_books_xlsx(
            contents, db, actor=actor, actor_role=actor_role, device_id=device_id
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .csv or .xlsx file.",
        )

    return result


@router.post("/batch-register", response_model=dict[str, Any])
def batch_register_books(
    books_data: list[BookCreate],
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    """
    Register multiple book copies in a batch (e.g. from Batch Scanning Queue).
    """
    if not books_data:
        raise HTTPException(status_code=400, detail="No book records provided.")

    existing_stocks = set(db.scalars(select(Book.stock_number)).all())
    batch_stocks = set()
    created_books: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, item in enumerate(books_data, start=1):
        if item.stock_number in existing_stocks or item.stock_number in batch_stocks:
            errors.append({
                "item_index": idx,
                "stock_number": item.stock_number,
                "error": f"Stock number '{item.stock_number}' is already in use.",
            })
            continue

        batch_stocks.add(item.stock_number)
        book = Book(
            serial_number=f"PENDING-{uuid4().hex}",
            device_id=device_id,
            **item.model_dump(),
        )
        db.add(book)
        db.flush()
        book.serial_number = f"UDY-{book.id:06d}"
        enqueue_change(
            db,
            operation="CREATE",
            entity_type="book",
            entity_id=book.id,
            payload=book_to_dict(book),
            device_id=device_id,
        )
        created_books.append(book_to_dict(book))

    if created_books:
        db.commit()
        log_action(
            db,
            "batch_registration_completed",
            None,
            {"count": len(created_books), "error_count": len(errors)},
            actor=current_user.email,
            actor_role=current_user.role,
            entity_type="bulk",
        )
        db.commit()

    return {
        "success": True,
        "created_count": len(created_books),
        "error_count": len(errors),
        "created_items": created_books,
        "errors": errors,
    }


# Database Backup and Restore Endpoints (Admin Only)
@router.get("/backup/download")
def download_database_backup(
    current_admin: User = Depends(require_admin),
):
    """
    (Administrator only) Download a verified snapshot copy of the database.
    """
    try:
        raw_bytes = create_database_backup_bytes()
        filename = f"udaya_library_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        return Response(
            content=raw_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backup generation failed: {exc}")


@router.post("/backup/restore")
async def restore_database(
    file: UploadFile = File(...),
    current_admin: User = Depends(require_admin),
):
    """
    (Administrator only) Restore the database from an uploaded .db backup file.
    Integrity and required tables are strictly verified before applying.
    """
    raw_bytes = await file.read()
    result = restore_database_from_bytes(
        raw_bytes=raw_bytes,
        actor=current_admin.email,
        actor_role=current_admin.role,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result
