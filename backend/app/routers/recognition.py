import json
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from typing import Any
from ..auth.dependencies import require_any_authenticated
from ..database import get_db
from ..metadata.classifier import suggest_category
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..models import Book, Category, User

from ..metadata.providers import search_metadata
from ..isbn import normalize_isbn
from ..recognition.service import process_recognition_image
from ..recognition import service as recognition_service

router = APIRouter(prefix="/api/recognition", tags=["recognition"])


def add_category_suggestions(candidates: list[dict[str, Any]], db: Session) -> list[dict[str, Any]]:
    categories = db.scalars(
        select(Category)
        .where(Category.parent_id.is_(None))
        .options(selectinload(Category.subcategories))
    ).all()
    hierarchy = [
        {
            "name": category.name,
            "subcategories": [{"name": sub.name} for sub in category.subcategories],
        }
        for category in categories
    ]
    for candidate in candidates:
        category, subcategory = suggest_category(candidate, hierarchy)
        candidate["category"] = category
        candidate["subcategory"] = subcategory
    return candidates


class BarcodeLookupRequest(BaseModel):
    barcode: str


class MetadataCandidate(BaseModel):
    title: str
    author: str | None = None
    publisher: str | None = None
    price: float | None = None
    price_source: str | None = None
    price_currency: str | None = None
    source: str
    subjects: list[str] = []
    category: str | None = None
    subcategory: str | None = None
    # Provider details remain candidate metadata; ISBN is retained for saving
    # and local repeat-copy matching.
    published_date: str | None = None
    publication_year: int | None = None
    edition: str | None = None
    language: str | None = None
    page_count: int | None = None
    description: str | None = None
    isbn: str | None = None
    subtitle: str | None = None
    editor: str | None = None
    translator: str | None = None
    series: str | None = None
    volume: str | None = None
    cover_image_url: str | None = None
    source_url: str | None = None
    field_provenance: dict[str, list[str]] = {}
    field_conflicts: dict[str, list[Any]] = {}
    local_copy_count: int | None = None
    match_status: str | None = None


class RecognitionResponse(BaseModel):
    success: bool
    message: str
    barcode: str | None = None
    ocr_available: bool = False
    ocr_lines: list[str] = []
    candidates: list[MetadataCandidate] = []


def _same_text(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def local_candidates(
    db: Session,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    normalized_isbn = normalize_isbn(isbn)
    requested_title = (title or query or "").strip()
    if not normalized_isbn and not requested_title:
        return []
    books = db.scalars(select(Book).where(Book.is_deleted.is_(False))).all()
    matches = []
    for book in books:
        if normalized_isbn:
            matches.append(book if book.isbn == normalized_isbn else None)
            continue
        if not requested_title or not _same_text(book.title, requested_title):
            continue
        if author is not None and not _same_text(book.author, author):
            continue
        matches.append(book)

    grouped: dict[tuple[Any, ...], list[Book]] = {}
    for book in (match for match in matches if match is not None):
        key = (
            book.isbn,
            book.title,
            book.author,
            book.publisher,
            book.edition,
            book.language,
        )
        grouped.setdefault(key, []).append(book)

    candidates = []
    for copies in grouped.values():
        book = copies[0]
        candidates.append({
            "title": book.title,
            "author": book.author,
            "publisher": book.publisher,
            "price": float(book.price) if book.price is not None else None,
            "price_currency": book.price_currency,
            "price_source": book.price_source,
            "source": f"Already in this library ({len(copies)} copies)",
            "subjects": [],
            "category": book.category,
            "subcategory": book.subcategory,
            "published_date": book.publication_date,
            "publication_year": book.publication_year,
            "edition": book.edition,
            "language": book.language,
            "page_count": book.page_count,
            "description": book.description,
            "isbn": book.isbn,
            "local_copy_count": len(copies),
        })
    return candidates


@router.post("/scan", response_model=RecognitionResponse)
async def scan_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Upload a book cover or barcode photo for recognition.
    Processes image strictly in-memory and discards it immediately.
    Never stores photos on disk or in the database.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be an image (JPEG, PNG, WebP, etc.).",
        )

    # Read bytes into memory (capped at 15MB to prevent abuse)
    image_bytes = await file.read()
    if len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image file exceeds 15MB limit.")

    async def local_first_lookup(**kwargs: Any) -> list[dict[str, Any]]:
        local = local_candidates(db, isbn=kwargs.get("isbn"))
        if local:
            return local
        return await recognition_service.search_metadata(**kwargs)

    result = await process_recognition_image(image_bytes, metadata_lookup=local_first_lookup)
    result["candidates"] = add_category_suggestions(result["candidates"], db)
    return result


@router.post("/barcode", response_model=list[MetadataCandidate])
async def lookup_barcode(
    payload: BarcodeLookupRequest,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Lookup book metadata directly by scanned barcode number.
    """
    candidates = local_candidates(db, isbn=payload.barcode)
    if not candidates:
        candidates = await search_metadata(isbn=payload.barcode)
    return add_category_suggestions(candidates, db)


@router.get("/lookup", response_model=list[MetadataCandidate])
async def lookup_metadata(
    response: Response,
    isbn: str | None = Query(default=None, description="ISBN-10 or ISBN-13"),
    title: str | None = Query(default=None, description="Book title"),
    author: str | None = Query(default=None, description="Author name"),
    publisher: str | None = Query(default=None, description="Known publisher"),
    q: str | None = Query(default=None, description="General search term"),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Search online metadata by ISBN, title, author, or keyword query.
    Uses multi-source fallback (Google Books & Open Library).
    """
    if not any([isbn, title, author, publisher, q]):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one search parameter (isbn, title, author, or q).",
        )

    candidates = local_candidates(db, isbn=isbn, title=title, author=author, query=q)
    if not candidates:
        candidates = await search_metadata(isbn=isbn, title=title, author=author, publisher=publisher, query=q)
    if response is not None and hasattr(candidates, "result_status"):
        response.headers["X-Metadata-Result-Status"] = candidates.result_status
        response.headers["X-Metadata-Provider-Status"] = json.dumps(
            candidates.provider_status, separators=(",", ":")
        )
    return add_category_suggestions(candidates, db)
