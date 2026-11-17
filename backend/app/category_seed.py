from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category


DEFAULT_CATEGORY_TREE: dict[str, list[str]] = {
    "Fiction": [
        "Literary Fiction",
        "Romance",
        "Mystery",
        "Thriller",
        "Fantasy",
        "Historical Fiction",
    ],
    "Non-Fiction": [
        "Self-Help",
        "Personal Development",
        "Psychology",
        "Philosophy",
        "General Knowledge",
    ],
    "Science": [
        "Physics",
        "Chemistry",
        "Biology",
        "Mathematics",
        "Astronomy",
        "Environment",
    ],
    "Technology & Engineering": [
        "Computer Science",
        "Electronics",
        "Electrical Engineering",
        "Mechanical Engineering",
        "Civil Engineering",
        "Artificial Intelligence & Robotics",
    ],
    "History & Geography": [
        "Indian History",
        "World History",
        "Kerala History",
        "Geography",
        "Politics",
    ],
    "Biography & Autobiography": [
        "Scientists",
        "Leaders",
        "Writers",
        "Other Personalities",
    ],
    "Literature": [
        "Poetry",
        "Drama",
        "Essays",
        "Literary Criticism",
    ],
    "Religion & Spirituality": [
        "Indian Philosophy",
        "Comparative Religion",
        "Spirituality",
        "Ethics",
    ],
    "Education & Reference": [
        "Textbooks",
        "Dictionaries",
        "Encyclopedias",
        "Competitive Examinations",
    ],
    "Children's Books": [
        "Stories",
        "Picture Books",
        "Educational Books",
        "Comics",
    ],
    "Language & Linguistics": [
        "English",
        "Malayalam",
        "Hindi",
        "Other Languages",
        "Grammar",
    ],
    "Arts & Culture": [
        "Art",
        "Music",
        "Photography",
        "Cinema",
        "Culture",
    ],
}


def _find_category(db: Session, name: str, parent_id: int | None) -> Category | None:
    return db.scalar(
        select(Category).where(
            Category.name == name,
            Category.parent_id == parent_id
            if parent_id is not None
            else Category.parent_id.is_(None),
        )
    )


def seed_default_categories(db: Session) -> int:
    """Create the approved two-level category tree without changing existing rows."""
    created = 0
    for category_name, subcategory_names in DEFAULT_CATEGORY_TREE.items():
        category = _find_category(db, category_name, None)
        if category is None:
            category = Category(name=category_name, parent_id=None)
            db.add(category)
            db.flush()
            created += 1

        for subcategory_name in subcategory_names:
            if _find_category(db, subcategory_name, category.id) is None:
                db.add(Category(name=subcategory_name, parent_id=category.id))
                created += 1

    if created:
        db.commit()
    return created
