from datetime import datetime, timezone
import re
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Book, Category, User
from ..schemas import BookCreate, BookUpdate, BookRead, BookList
from ..services import book_to_dict, log_action, enqueue_change
from ..auth.dependencies import (
    get_authenticated_device_id,
    require_any_authenticated,
)

router = APIRouter(prefix="/api/books", tags=["books"])


def _stock_number_suggestion(stock_numbers: list[str]) -> str:
    trailing = []
    for stock in stock_numbers:
        match = re.match(r"^(.*?)(\d+)$", stock.strip())
        if match:
            trailing.append((match.group(1), int(match.group(2)), len(match.group(2))))
    if trailing:
        prefix, _, width = max(trailing, key=lambda item: item[1])
        next_number = max(number for item_prefix, number, _ in trailing if item_prefix == prefix) + 1
        return f"{prefix}{next_number:0{width}d}"

    numbers = [int(value) for stock in stock_numbers for value in re.findall(r"\d+", stock)]
    return str(max(numbers, default=0) + 1)


@router.get("/stock-number/suggestion")
def suggest_stock_number(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    existing = db.scalars(select(Book.stock_number)).all()
    suggestion = _stock_number_suggestion(existing)
    while db.scalar(select(Book.id).where(Book.stock_number == suggestion)) is not None:
        match = re.match(r"^(.*?)(\d+)$", suggestion)
        suggestion = f"{match.group(1)}{int(match.group(2)) + 1}" if match else f"{suggestion}1"
    return {"stock_number": suggestion}


@router.get("/stock-number/check")
def check_stock_number(
    stock_number: str = Query(min_length=1, max_length=100),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    book = db.scalar(select(Book).where(Book.stock_number == stock_number.strip()))
    return {
        "stock_number": stock_number.strip(),
        "used": book is not None,
        "title": book.title if book else None,
        "book_id": book.id if book else None,
    }


@router.get("/meta/categories")
def list_categories(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    result: dict[str, list[str]] = {}

    # 1. Categories defined in the managed Category table
    managed_cats = db.execute(select(Category).where(Category.parent_id.is_(None))).scalars().all()
    for cat in managed_cats:
        result.setdefault(cat.name, [])
        for sub in cat.subcategories:
            if sub.name not in result[cat.name]:
                result[cat.name].append(sub.name)

    # 2. Plus any categories present in books
    rows = db.execute(
        select(Book.category, Book.subcategory).where(
            Book.is_deleted.is_(False), Book.category.is_not(None)
        )
    ).all()
    for category, subcategory in rows:
        result.setdefault(category, [])
        if subcategory and subcategory not in result[category]:
            result[category].append(subcategory)
    return result


@router.get("/deleted", response_model=BookList)
def list_deleted_books(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    stmt = select(Book).where(Book.is_deleted.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    books = db.scalars(
        stmt.order_by(Book.deleted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [book_to_dict(b) for b in books],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("", response_model=BookList)
def list_books(
    q: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    incomplete_only: bool = False,
    sort_by: str = Query(default="id", pattern="^(id|title|author|stock_number|serial_number|price|created_at)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
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
            Book.publisher.ilike(pattern),
            Book.category.ilike(pattern),
            Book.subcategory.ilike(pattern),
        ))
    if category:
        stmt = stmt.where(Book.category == category)
    if subcategory:
        stmt = stmt.where(Book.subcategory == subcategory)
    if min_price is not None:
        stmt = stmt.where(Book.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Book.price <= max_price)
    if incomplete_only:
        stmt = stmt.where(or_(
            Book.author.is_(None), Book.author == "",
            Book.publisher.is_(None), Book.publisher == "",
            Book.category.is_(None), Book.category == "",
            Book.subcategory.is_(None), Book.subcategory == "",
            Book.price.is_(None),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # Dynamic column sorting
    col = getattr(Book, sort_by, Book.id)
    order_clause = col.desc() if sort_order.lower() == "desc" else col.asc()

    books = db.scalars(
        stmt.order_by(order_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [book_to_dict(b) for b in books],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=BookRead, status_code=201)
def create_book(
    payload: BookCreate,
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    book = Book(
        serial_number=f"PENDING-{uuid4().hex}",
        version=1,
        device_id=device_id,
        **payload.model_dump(),
    )
    db.add(book)
    try:
        db.flush()
        book.serial_number = f"UDY-{book.id:06d}"
        log_action(
            db,
            "book_created",
            book.id,
            {
                "serial_number": book.serial_number,
                "stock_number": book.stock_number,
                "title": book.title,
            },
            actor=current_user.email,
            actor_role=current_user.role,
            device_id=device_id,
        )
        enqueue_change(
            db,
            operation="CREATE",
            entity_type="book",
            entity_id=book.id,
            payload=book_to_dict(book),
            device_id=device_id,
        )
        db.commit()
        db.refresh(book)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This stock number is already in use.")
    return book_to_dict(book)


@router.patch("/{book_id}/restore", response_model=BookRead)
def restore_book(
    book_id: int,
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    if current_user.role == "restricted_librarian":
        raise HTTPException(status_code=403, detail="Restricted librarians cannot restore deleted books.")
    book = db.get(Book, book_id)
    if not book or not book.is_deleted:
        raise HTTPException(status_code=404, detail="Deleted book not found")
    book.is_deleted = False
    book.deleted_at = None
    book.version = (book.version or 1) + 1
    book.device_id = device_id
    log_action(
        db,
        "book_restored",
        book.id,
        {
            "serial_number": book.serial_number,
            "stock_number": book.stock_number,
            "title": book.title,
        },
        actor=current_user.email,
        actor_role=current_user.role,
        device_id=device_id,
    )
    enqueue_change(
        db,
        operation="RESTORE",
        entity_type="book",
        entity_id=book.id,
        payload={"stock_number": book.stock_number, "version": book.version},
        device_id=device_id,
    )
    db.commit()
    db.refresh(book)
    return book_to_dict(book)


@router.patch("/{book_id}", response_model=BookRead)
def update_book(
    book_id: int,
    payload: BookUpdate,
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    book = db.get(Book, book_id)
    if not book or book.is_deleted:
        raise HTTPException(status_code=404, detail="Book not found")
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(book, key) for key in changes}
    for key, value in changes.items():
        setattr(book, key, value)
    book.version = (book.version or 1) + 1
    book.device_id = device_id
    try:
        log_action(
            db,
            "book_updated",
            book.id,
            {"before": before, "after": changes},
            actor=current_user.email,
            actor_role=current_user.role,
            device_id=device_id,
        )
        enqueue_change(
            db,
            operation="UPDATE",
            entity_type="book",
            entity_id=book.id,
            payload=book_to_dict(book),
            device_id=device_id,
        )
        db.commit()
        db.refresh(book)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This stock number is already in use.")
    return book_to_dict(book)


@router.delete("/{book_id}", status_code=204)
def delete_book(
    book_id: int,
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    if current_user.role == "restricted_librarian":
        raise HTTPException(status_code=403, detail="Restricted librarians cannot delete books.")
    book = db.get(Book, book_id)
    if not book or book.is_deleted:
        raise HTTPException(status_code=404, detail="Book not found")
    book.is_deleted = True
    book.deleted_at = datetime.now(timezone.utc)
    book.version = (book.version or 1) + 1
    book.device_id = device_id
    log_action(
        db,
        "book_deleted",
        book.id,
        {
            "serial_number": book.serial_number,
            "stock_number": book.stock_number,
            "title": book.title,
        },
        actor=current_user.email,
        actor_role=current_user.role,
        device_id=device_id,
    )
    enqueue_change(
        db,
        operation="DELETE",
        entity_type="book",
        entity_id=book.id,
        payload={"stock_number": book.stock_number, "version": book.version},
        device_id=device_id,
    )
    db.commit()
    return None
