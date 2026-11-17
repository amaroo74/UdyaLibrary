from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Category, Book, User
from ..schemas import CategoryCreate, CategoryRead, CategoryHierarchy
from ..services import log_action
from ..auth.dependencies import require_any_authenticated, require_librarian

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryHierarchy])
def list_categories(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    List all top-level categories and their subcategories in hierarchy.
    """
    # Fetch root categories with subcategories eagerly loaded
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None))
        .options(selectinload(Category.subcategories))
        .order_by(Category.name.asc())
    )
    categories = db.scalars(stmt).all()

    result = []
    for cat in categories:
        result.append(
            CategoryHierarchy(
                id=cat.id,
                name=cat.name,
                subcategories=[
                    CategoryRead(id=sub.id, name=sub.name, parent_id=sub.parent_id)
                    for sub in sorted(cat.subcategories, key=lambda s: s.name.lower())
                ],
            )
        )
    return result


@router.post("", response_model=CategoryRead, status_code=201)
def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(require_librarian),
    db: Session = Depends(get_db),
):
    """
    Create a new category (parent_id is None) or subcategory (parent_id is valid category ID).
    """
    if payload.parent_id is not None:
        parent = db.get(Category, payload.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")
        # Subcategories cannot have nested subcategories (keep 2-tier hierarchy simple and clean)
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Multi-level nesting beyond subcategories is not supported.",
            )

    # Check for duplicate sibling names
    stmt = select(Category).where(
        Category.name.ilike(payload.name),
        Category.parent_id == payload.parent_id
        if payload.parent_id is not None
        else Category.parent_id.is_(None),
    )
    existing = db.scalar(stmt)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A category with name '{payload.name}' already exists here.",
        )

    cat = Category(name=payload.name, parent_id=payload.parent_id)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    log_action(db, "category_created", cat.id, {"name": cat.name, "parent_id": cat.parent_id})
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    current_user: User = Depends(require_librarian),
    db: Session = Depends(get_db),
):
    """
    Delete a category or subcategory.
    """
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    log_action(db, "category_deleted", cat.id, {"name": cat.name, "parent_id": cat.parent_id})
    db.delete(cat)
    db.commit()
    return None
