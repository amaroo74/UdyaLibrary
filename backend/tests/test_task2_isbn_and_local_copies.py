from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.main import app
from app.metadata.providers import normalize_candidate
from app.models import UserRole


ISBN13 = "9780143424123"
OTHER_ISBN13 = "9780306406157"


def client():
    token = create_access_token(
        user_id=1,
        email="admin@udayalibrary.org",
        role=UserRole.ADMINISTRATOR.value,
        name="Test Administrator",
        device_id="task2-device",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def book_payload(stock_number: str, isbn: str | None = ISBN13) -> dict:
    return {
        "stock_number": stock_number,
        "title": "The 3 Mistakes of My Life",
        "author": "Chetan Bhagat",
        "publisher": "Rupa Publications",
        "isbn": isbn,
        "publication_date": "2008",
        "publication_year": 2008,
        "edition": "First edition",
        "language": "en",
        "page_count": 258,
        "description": "A novel.",
        "category": "Fiction",
        "subcategory": "Novel",
        "price": 12.5,
        "price_currency": "USD",
        "price_source": "Fixture provider",
    }


def test_isbn10_normalizes_to_isbn13():
    candidate = normalize_candidate(
        title="Fixture",
        isbn="0-14-342412-2",
    )
    assert candidate["isbn"] == ISBN13


def test_local_isbn_candidate_is_first_and_provider_is_not_called(monkeypatch):
    api = client()
    first = api.post("/api/books", json=book_payload(f"TASK2-{uuid4().hex[:8]}"))
    assert first.status_code == 201

    calls = []

    async def provider_should_not_run(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr("app.routers.recognition.search_metadata", provider_should_not_run)
    lookup = api.get(f"/api/recognition/lookup?isbn={ISBN13}")
    assert lookup.status_code == 200
    candidates = lookup.json()
    assert candidates[0]["source"] == "Already in this library (1 copies)"
    assert candidates[0]["isbn"] == ISBN13
    assert calls == []

    second_stock = f"TASK2-{uuid4().hex[:8]}"
    second = api.post(
        "/api/books",
        json={"stock_number": second_stock, **{
            key: candidates[0][key]
            for key in (
                "title", "author", "publisher", "isbn", "published_date",
                "publication_year", "edition", "language", "page_count",
                "description", "category", "subcategory", "price",
                "price_currency", "price_source",
            )
        }},
    )
    assert second.status_code == 201
    rows = api.get(f"/api/books?q={second_stock}").json()["items"]
    assert rows[0]["stock_number"] == second_stock
    assert rows[0]["isbn"] == ISBN13


def test_provider_isbn_lookup_save_reopen_preserves_isbn(monkeypatch):
    api = client()
    candidate = {
        "title": "New Fixture Book",
        "author": "New Author",
        "publisher": "New Publisher",
        "isbn": ISBN13,
        "price": None,
        "price_source": None,
        "price_currency": None,
        "source": "Fixture provider",
        "subjects": [],
        "category": None,
        "subcategory": None,
        "published_date": None,
        "publication_year": None,
        "edition": "First edition",
        "language": "en",
        "page_count": None,
        "description": None,
    }

    async def provider_result(**kwargs):
        return [candidate]

    monkeypatch.setattr("app.routers.recognition.search_metadata", provider_result)
    lookup = api.get(f"/api/recognition/lookup?isbn={ISBN13}")
    assert lookup.status_code == 200
    selected = lookup.json()[0]
    stock = f"TASK2-{uuid4().hex[:8]}"
    saved = api.post(
        "/api/books",
        json={"stock_number": stock, "title": selected["title"], "author": selected["author"],
              "publisher": selected["publisher"], "isbn": selected["isbn"],
              "edition": selected["edition"], "language": selected["language"]},
    )
    assert saved.status_code == 201
    reopened = api.get(f"/api/books?q={stock}").json()["items"][0]
    assert reopened["isbn"] == ISBN13


def test_local_title_author_match_uses_full_bibliographic_group():
    api = client()
    title = f"Local title {uuid4().hex[:8]}"
    payload = book_payload(f"TASK2-{uuid4().hex[:8]}", isbn=None)
    payload["title"] = title
    first = api.post("/api/books", json=payload)
    assert first.status_code == 201

    lookup = api.get(
        f"/api/recognition/lookup?title={title.replace(' ', '+')}&author=Chetan+Bhagat"
    )
    assert lookup.status_code == 200
    assert lookup.json()[0]["source"] == "Already in this library (1 copies)"
    assert lookup.json()[0]["isbn"] is None


def test_different_isbn_is_not_offered_as_local_copy(monkeypatch):
    api = client()
    first = api.post("/api/books", json=book_payload(f"TASK2-{uuid4().hex[:8]}"))
    assert first.status_code == 201

    async def provider_result(**kwargs):
        return [{
            "title": "Different Edition",
            "author": "Chetan Bhagat",
            "publisher": "Rupa Publications",
            "isbn": OTHER_ISBN13,
            "price": None,
            "price_source": None,
            "price_currency": None,
            "source": "Fixture provider",
            "subjects": [],
            "category": None,
            "subcategory": None,
            "published_date": None,
            "publication_year": None,
            "edition": "Second edition",
            "language": "en",
            "page_count": None,
            "description": None,
        }]

    monkeypatch.setattr("app.routers.recognition.search_metadata", provider_result)
    lookup = api.get(f"/api/recognition/lookup?isbn={OTHER_ISBN13}")
    assert lookup.status_code == 200
    assert lookup.json()[0]["source"] == "Fixture provider"
    assert lookup.json()[0]["isbn"] == OTHER_ISBN13


def test_duplicate_stock_number_is_rejected():
    api = client()
    stock = f"TASK2-{uuid4().hex[:8]}"
    assert api.post("/api/books", json=book_payload(stock)).status_code == 201
    duplicate = api.post("/api/books", json=book_payload(stock))
    assert duplicate.status_code == 409
