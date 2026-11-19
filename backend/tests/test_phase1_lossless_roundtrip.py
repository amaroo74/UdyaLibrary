import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.main import app
from app.metadata import providers
from app.models import UserRole


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FixtureClient:
    responses = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, **kwargs):
        return FixtureResponse(self.responses[url])


def auth_headers():
    token = create_access_token(
        user_id=1,
        email="admin@udayalibrary.org",
        role=UserRole.ADMINISTRATOR.value,
        name="Test Administrator",
        device_id="phase1-device",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_real_isbn_provider_fixtures_preserve_bibliographic_metadata(monkeypatch):
    google = json.loads((FIXTURES / "google_books_9780143424123.json").read_text())
    open_library = json.loads((FIXTURES / "open_library_9780143424123.json").read_text())
    FixtureClient.responses = {
        "https://www.googleapis.com/books/v1/volumes": google,
        "https://openlibrary.org/isbn/9780143424123.json": open_library,
        "https://openlibrary.org/authors/OL123A.json": {"name": "Chetan Bhagat"},
    }
    monkeypatch.setattr(providers.httpx, "AsyncClient", FixtureClient)

    result = await providers.query_google_books(
        FixtureClient(), isbn="978-0-14-342412-3"
    )

    candidate = result[0]
    assert candidate["title"] == "The 3 Mistakes of My Life"
    assert candidate["author"] == "Chetan Bhagat"
    assert candidate["publisher"] == "Rupa Publications"
    assert candidate["published_date"] == "2008-01-01"
    assert candidate["publication_year"] == 2008
    assert candidate["language"] == "en"
    assert candidate["page_count"] == 258
    assert candidate["description"]
    assert candidate["price"] == 12.5
    assert candidate["price_currency"] == "USD"

    open_library_candidate = (
        await providers.query_open_library(
            FixtureClient(), isbn="978-0-14-342412-3"
        )
    )[0]
    assert open_library_candidate["title"] == candidate["title"]
    assert open_library_candidate["author"] == candidate["author"]
    assert open_library_candidate["publisher"] == candidate["publisher"]
    assert open_library_candidate["page_count"] == candidate["page_count"]
    assert open_library_candidate["price"] is None
    assert open_library_candidate["price_currency"] is None


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(500, "INR"), (12.5, "USD"), (15, "EUR"), (20, None)],
)
def test_api_lookup_pick_save_reopen_preserves_amount_and_currency(
    monkeypatch, amount, currency
):
    candidate = {
        "title": "Fixture Book",
        "author": "Fixture Author",
        "publisher": "Fixture Publisher",
        "price": amount,
        "price_source": "Fixture provider",
        "price_currency": currency,
        "source": "Fixture provider",
        "subjects": ["Fiction"],
        "category": "Fiction",
        "subcategory": "Novel",
        "published_date": "2008-01-01",
        "publication_year": 2008,
        "edition": "First edition",
        "language": "en",
        "page_count": 258,
        "description": "Fixture description.",
    }
    async def fake_search_metadata(**kwargs):
        return [candidate]

    monkeypatch.setattr("app.routers.recognition.search_metadata", fake_search_metadata)
    client = TestClient(app, headers=auth_headers())

    lookup = client.get("/api/recognition/lookup?isbn=9780143424123")
    assert lookup.status_code == 200
    selected = lookup.json()[0]

    payload = {
        "stock_number": f"PHASE1-{currency or 'UNKNOWN'}",
        "title": selected["title"],
        "author": selected["author"],
        "publisher": selected["publisher"],
        "publication_date": selected["published_date"],
        "publication_year": selected["publication_year"],
        "edition": selected["edition"],
        "language": selected["language"],
        "page_count": selected["page_count"],
        "description": selected["description"],
        "category": selected["category"],
        "subcategory": selected["subcategory"],
        "price": selected["price"],
        "price_currency": selected["price_currency"],
        "price_source": selected["price_source"],
    }
    saved = client.post("/api/books", json=payload)
    assert saved.status_code == 201
    saved_book = saved.json()

    reopened = client.get(f"/api/books?q={payload['stock_number']}")
    assert reopened.status_code == 200
    book = reopened.json()["items"][0]
    for field in (
        "title",
        "author",
        "publisher",
        "publication_date",
        "publication_year",
        "edition",
        "language",
        "page_count",
        "description",
        "category",
        "subcategory",
        "price",
        "price_currency",
    ):
        if field == "price":
            assert Decimal(book[field]) == Decimal(saved_book[field]) == Decimal(str(payload[field]))
        else:
            assert book[field] == saved_book[field] == payload[field]


def test_api_lookup_pick_save_reopen_allows_second_copy_with_same_metadata(monkeypatch):
    candidate = {
        "title": "The 3 Mistakes of My Life",
        "author": "Chetan Bhagat",
        "publisher": "Rupa Publications",
        "price": 12.5,
        "price_source": "Fixture provider",
        "price_currency": "USD",
        "source": "Fixture provider",
        "subjects": ["Fiction"],
        "category": "Fiction",
        "subcategory": "Novel",
        "published_date": "2008-01-01",
        "publication_year": 2008,
        "edition": "First edition",
        "language": "en",
        "page_count": 258,
        "description": "Fixture description.",
    }

    async def fake_search_metadata(**kwargs):
        return [candidate]

    monkeypatch.setattr("app.routers.recognition.search_metadata", fake_search_metadata)
    client = TestClient(app, headers=auth_headers())

    lookup = client.get("/api/recognition/lookup?isbn=9780143424123")
    assert lookup.status_code == 200
    selected = lookup.json()[0]
    metadata = {
        "title": selected["title"],
        "author": selected["author"],
        "publisher": selected["publisher"],
        "publication_date": selected["published_date"],
        "publication_year": selected["publication_year"],
        "edition": selected["edition"],
        "language": selected["language"],
        "page_count": selected["page_count"],
        "description": selected["description"],
        "category": selected["category"],
        "subcategory": selected["subcategory"],
        "price": selected["price"],
        "price_currency": selected["price_currency"],
        "price_source": selected["price_source"],
    }

    first = client.post(
        "/api/books",
        json={"stock_number": "PHASE1-COPY-1", **metadata},
    )
    assert first.status_code == 201
    first_reopened = client.get("/api/books?q=PHASE1-COPY-1")
    assert first_reopened.status_code == 200
    first_book = first_reopened.json()["items"][0]

    second = client.post(
        "/api/books",
        json={"stock_number": "PHASE1-COPY-2", **{
            key: first_book[key]
            for key in metadata
        }},
    )
    assert second.status_code == 201
    second_reopened = client.get("/api/books?q=PHASE1-COPY-2")
    assert second_reopened.status_code == 200
    second_book = second_reopened.json()["items"][0]

    for field in metadata:
        if field == "price":
            assert Decimal(second_book[field]) == Decimal(str(metadata[field]))
        else:
            assert second_book[field] == metadata[field]
