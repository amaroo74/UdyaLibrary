from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from typing import Any
from ..auth.dependencies import require_any_authenticated
from ..database import get_db
from ..metadata.classifier import suggest_category
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..models import User
from ..models import Category

from ..metadata.providers import search_metadata
from ..recognition.service import process_recognition_image

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
    source: str
    subjects: list[str] = []
    category: str | None = None
    subcategory: str | None = None


class RecognitionResponse(BaseModel):
    success: bool
    message: str
    barcode: str | None = None
    ocr_available: bool = False
    ocr_lines: list[str] = []
    candidates: list[MetadataCandidate] = []


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

    result = await process_recognition_image(image_bytes)
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
    candidates = await search_metadata(isbn=payload.barcode)
    return add_category_suggestions(candidates, db)


@router.get("/lookup", response_model=list[MetadataCandidate])
async def lookup_metadata(
    isbn: str | None = Query(default=None, description="ISBN-10 or ISBN-13"),
    title: str | None = Query(default=None, description="Book title"),
    author: str | None = Query(default=None, description="Author name"),
    q: str | None = Query(default=None, description="General search term"),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Search online metadata by ISBN, title, author, or keyword query.
    Uses multi-source fallback (Google Books & Open Library).
    """
    if not any([isbn, title, author, q]):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one search parameter (isbn, title, author, or q).",
        )

    candidates = await search_metadata(isbn=isbn, title=title, author=author, query=q)
    return add_category_suggestions(candidates, db)
