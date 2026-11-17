from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.category_seed import DEFAULT_CATEGORY_TREE, seed_default_categories
from app.models import Base, Book, Category


def test_category_seed_is_complete_idempotent_and_preserves_existing_rows():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        existing_parent = Category(name="Science", parent_id=None)
        existing_child = Category(name="Physics", parent=existing_parent)
        existing_book = Book(
            serial_number="SERIAL-SEED-1",
            stock_number="STOCK-SEED-1",
            title="Existing Physics Book",
            category="Science",
            subcategory="Physics",
        )
        db.add_all([existing_parent, existing_child, existing_book])
        db.commit()
        parent_id = existing_parent.id
        child_id = existing_child.id

        first_created = seed_default_categories(db)
        second_created = seed_default_categories(db)

        assert first_created == sum(len(items) + 1 for items in DEFAULT_CATEGORY_TREE.values()) - 2
        assert second_created == 0
        assert db.get(Category, parent_id).name == "Science"
        assert db.get(Category, child_id).name == "Physics"
        assert db.get(Book, existing_book.id).category == "Science"
        assert db.get(Book, existing_book.id).subcategory == "Physics"
        assert db.scalar(
            select(Category).where(
                Category.name == "Self-Help",
                Category.parent.has(name="Non-Fiction"),
            )
        ) is not None
