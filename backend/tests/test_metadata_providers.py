import httpx
import pytest

from app.metadata import providers


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    responses: dict[str, object] = {}
    calls: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        type(self).calls = self.calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, **kwargs):
        self.calls.append((url, params or {}))
        response = self.responses.get(url)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(url, params or {})
        return response or FakeResponse(200, {})


def install_fake_client(monkeypatch, responses):
    FakeAsyncClient.responses = responses
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeAsyncClient)


@pytest.mark.asyncio
async def test_google_books_success_and_title_author_search(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {
                    "items": [
                        {
                            "volumeInfo": {
                                "title": "Ikigai",
                                "authors": ["Héctor García", "Francesc Miralles"],
                                "publisher": "Penguin",
                            }
                        }
                    ]
                },
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    results = await providers.search_metadata(title="Ikigai", author="Héctor García")

    assert results[0]["title"] == "Ikigai"
    assert results[0]["author"] == "Héctor García, Francesc Miralles"
    google_call = next(call for call in FakeAsyncClient.calls if "googleapis" in call[0])
    assert 'intitle:"Ikigai"' in google_call[1]["q"]
    assert 'inauthor:"Héctor García"' in google_call[1]["q"]


@pytest.mark.asyncio
async def test_open_library_fallback_when_google_fails(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(503, {}),
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {"docs": [{"title": "Ikigai", "author_name": ["Héctor García"], "publisher": ["Penguin"]}]},
            ),
        },
    )

    results = await providers.search_metadata(query="Ikigai")

    assert results == [
        {
            "title": "Ikigai",
            "author": "Héctor García",
            "publisher": "Penguin",
            "price": None,
            "price_source": None,
            "source": "Open Library",
            "subjects": [],
        }
    ]


@pytest.mark.asyncio
async def test_timeout_and_malformed_google_response_still_use_open_library(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": httpx.TimeoutException("timed out"),
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {"docs": [{"title": "Ikigai", "author_name": ["Héctor García"]}]},
            ),
        },
    )
    results = await providers.search_metadata(title="Ikigai")
    assert results[0]["source"] == "Open Library"

    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(200, ["malformed"]),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )
    assert await providers.search_metadata(title="Unknown title") == []


@pytest.mark.asyncio
async def test_isbn_search_and_duplicate_results_preserve_distinct_publishers(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {
                    "items": [
                        {"volumeInfo": {"title": "Ikigai", "authors": ["Héctor García"], "publisher": "Penguin"}},
                        {"volumeInfo": {"title": "Ikigai", "authors": ["Héctor García"], "publisher": "Penguin"}},
                        {"volumeInfo": {"title": "Ikigai", "authors": ["Héctor García"], "publisher": "Random House"}},
                    ]
                },
            ),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(404, {}),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    results = await providers.search_metadata(isbn="978-0-14-342412-3")

    assert len(results) == 2
    google_call = next(call for call in FakeAsyncClient.calls if "googleapis" in call[0])
    assert google_call[1]["q"] == "isbn:9780143424123"


@pytest.mark.asyncio
async def test_no_results_returns_empty_list(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(200, {}),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )
    assert await providers.search_metadata(title="No Such Book") == []


@pytest.mark.asyncio
async def test_matching_provider_records_are_enriched_without_overwriting_price(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {
                    "items": [
                        {
                            "volumeInfo": {
                                "title": "Ikigai",
                                "authors": ["Héctor García"],
                                "industryIdentifiers": [
                                    {"type": "ISBN_13", "identifier": "9781234567890"}
                                ],
                            },
                            "saleInfo": {
                                "retailPrice": {"amount": 499, "currencyCode": "INR"}
                            },
                        }
                    ]
                },
            ),
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {
                    "docs": [
                        {
                            "title": "Ikigai",
                            "author_name": ["Héctor García"],
                            "publisher": ["Penguin"],
                            "isbn": ["9781234567890"],
                        }
                    ]
                },
            ),
        },
    )

    results = await providers.search_metadata(query="Ikigai")

    assert len(results) == 1
    assert results[0]["publisher"] == "Penguin"
    assert results[0]["price"] == 499
    assert "Google Books" in results[0]["source"]
    assert "Open Library" in results[0]["source"]
