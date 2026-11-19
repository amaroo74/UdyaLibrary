from uuid import uuid4

from app.routers.books import _stock_number_suggestion
from app.routers.recognition import local_candidates
from app.models import Book

from test_phase4_recognition import client, create_test_barcode_image


def test_barcode_scan_uses_local_catalogue_before_provider(monkeypatch):
    isbn = "9780143424123"
    stock = f"TASK3-BARCODE-{uuid4().hex[:8]}"
    created = client.post(
        "/api/books",
        json={"stock_number": stock, "title": "Local Barcode Book", "isbn": isbn, "author": "Local Author"},
    )
    assert created.status_code == 201

    async def provider_should_not_run(**kwargs):
        raise AssertionError("provider lookup should not run for a local barcode match")

    monkeypatch.setattr("app.recognition.service.search_metadata", provider_should_not_run)
    response = client.post(
        "/api/recognition/scan",
        files={"file": ("barcode.png", create_test_barcode_image(isbn), "image/png")},
    )

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates[0]["source"].startswith("Already in this library (")
    assert candidates[0]["local_copy_count"] >= 1
    assert candidates[0]["isbn"] == isbn


def test_stock_number_suggestion_preserves_numeric_pattern_and_gaps():
    assert _stock_number_suggestion(["LIB-001", "LIB-003"]) == "LIB-004"
    assert _stock_number_suggestion([]) == "1"


def test_stock_number_check_reports_owner_title():
    stock = f"TASK3-CHECK-{uuid4().hex[:8]}"
    created = client.post("/api/books", json={"stock_number": stock, "title": "Owned Stock Book"})
    assert created.status_code == 201

    used = client.get("/api/books/stock-number/check", params={"stock_number": stock})
    assert used.status_code == 200
    assert used.json()["used"] is True
    assert used.json()["title"] == "Owned Stock Book"

    unused = client.get("/api/books/stock-number/check", params={"stock_number": f"{stock}-NEW"})
    assert unused.status_code == 200
    assert unused.json()["used"] is False
    assert unused.json()["title"] is None


def test_title_only_local_matches_keep_different_authors_separate():
    title = f"Same Title {uuid4().hex[:8]}"
    first = Book(
        serial_number=f"UDY-{uuid4().hex[:8]}",
        stock_number=f"TASK3-TITLE-A-{uuid4().hex[:8]}",
        title=title,
        author="Author One",
        publisher="Publisher One",
        publication_year=2001,
        isbn="9780143424123",
    )
    second = Book(
        serial_number=f"UDY-{uuid4().hex[:8]}",
        stock_number=f"TASK3-TITLE-B-{uuid4().hex[:8]}",
        title=title,
        author="Author Two",
        publisher="Publisher Two",
        publication_year=2002,
        isbn="9780306406157",
    )
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.add_all([first, second])
        db.commit()
        candidates = local_candidates(db, query=title)
    finally:
        db.close()

    assert {candidate["author"] for candidate in candidates} == {"Author One", "Author Two"}
    assert {candidate["publisher"] for candidate in candidates} == {"Publisher One", "Publisher Two"}
    assert {candidate["publication_year"] for candidate in candidates} == {2001, 2002}
    assert {candidate["isbn"] for candidate in candidates} == {"9780143424123", "9780306406157"}
