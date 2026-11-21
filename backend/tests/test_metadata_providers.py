import httpx
import pytest

from app.metadata import providers


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else ""

    def json(self):
        return self._payload


class FakeAsyncClient:
    responses: dict[str, object] = {}
    calls: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.call_details = []
        type(self).calls = self.calls
        type(self).call_details = self.call_details

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, **kwargs):
        self.calls.append((url, params or {}))
        self.call_details.append((url, params or {}, kwargs))
        response = self.responses.get(url)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(url, params or {})
        return response or FakeResponse(200, {})


def install_fake_client(monkeypatch, responses):
    FakeAsyncClient.responses = responses
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeAsyncClient)


def wikidata_fixture_response(url, params):
    action = params.get("action")
    if action == "wbsearchentities":
        title = "Fixture Exact" if params.get("search") == "9780143424123" else "Fixture Search"
        qid = "QISBN" if title == "Fixture Exact" else "QSEARCH"
        return FakeResponse(200, {"search": [{"id": qid, "label": title}]})
    if action == "wbgetentities" and params.get("props") == "labels":
        return FakeResponse(200, {"entities": {
            "Q2": {"labels": {"en": {"value": "Fixture Author"}}},
            "Q3": {"labels": {"en": {"value": "Fixture Publisher"}}},
        }})
    title = "Fixture Exact" if "QISBN" in params.get("ids", "") else "Fixture Search"
    claims = {
        "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}],
        "P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}],
        "P123": [{"mainsnak": {"datavalue": {"value": {"id": "Q3"}}}}],
    }
    if title == "Fixture Exact":
        claims["P957"] = [{"mainsnak": {"datavalue": {"value": "9780143424123"}}}]
    qid = "QISBN" if title == "Fixture Exact" else "QSEARCH"
    return FakeResponse(200, {"entities": {qid: {
        "labels": {"en": {"value": title}},
        "claims": claims,
    }}})


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
            "price_currency": None,
            "source": "Open Library",
            "subjects": [],
            "published_date": None,
            "publication_year": None,
            "edition": None,
            "language": None,
            "page_count": None,
            "description": None,
            "isbn": None,
            "subtitle": None,
            "editor": None,
            "translator": None,
            "series": None,
            "volume": None,
            "cover_image_url": None,
            "field_provenance": {
                "title": ["Open Library"],
                "author": ["Open Library"],
                "publisher": ["Open Library"],
            },
            "field_conflicts": {},
            "match_status": "unverified_search",
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
                        {                        "volumeInfo": {
                            "title": "Ikigai",
                            "authors": ["Héctor García"],
                            "publisher": "Penguin",
                            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780143424123"}],
                        }},
                        {"volumeInfo": {
                        "title": "Ikigai",
                        "authors": ["Héctor García"],
                        "publisher": "Penguin",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780143424123"}],
                        }},
                        {"volumeInfo": {
                        "title": "Ikigai",
                        "authors": ["Héctor García"],
                        "publisher": "Random House",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780143424123"}],
                        }},
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("currency_code", "expected_currency", "expected_source"),
    [
        ("INR", "INR", "Google Books (INR)"),
        ("USD", "USD", "Google Books (USD)"),
        ("EUR", "EUR", "Google Books (EUR)"),
        (None, None, "Google Books (currency unknown)"),
        ("XYZ", "XYZ", "Google Books (XYZ)"),
    ],
)
async def test_google_books_preserves_original_price_currency(
    monkeypatch, currency_code, expected_currency, expected_source
):
    sale_info = {"retailPrice": {"amount": 500, "currencyCode": currency_code}}
    if currency_code is None:
        sale_info["retailPrice"].pop("currencyCode")
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {"items": [{"volumeInfo": {"title": "Currency Test"}, "saleInfo": sale_info}]},
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    result = (await providers.search_metadata(title="Currency Test"))[0]

    assert result["price"] == 500
    assert result["price_currency"] == expected_currency
    assert result["price_source"] == expected_source


@pytest.mark.asyncio
async def test_missing_price_has_no_currency(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200, {"items": [{"volumeInfo": {"title": "No Price"}}]}
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    result = (await providers.search_metadata(title="No Price"))[0]

    assert result["price"] is None
    assert result["price_currency"] is None
    assert result["price_source"] is None


@pytest.mark.asyncio
async def test_provider_details_are_returned_as_candidate_metadata(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {
                    "items": [
                        {
                            "volumeInfo": {
                                "title": "Wings of Fire",
                                "authors": ["A.P.J. Abdul Kalam"],
                                "publisher": "Universities Press",
                                "publishedDate": "1999",
                                "language": "en",
                                "pageCount": 180,
                                "description": "An autobiography.",
                            }
                        }
                    ]
                },
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    results = await providers.search_metadata(title="Wings of Fire")

    assert results[0]["published_date"] == "1999"
    assert results[0]["publication_year"] == 1999
    assert results[0]["language"] == "en"
    assert results[0]["page_count"] == 180
    assert results[0]["description"] == "An autobiography."


@pytest.mark.asyncio
async def test_complementary_fields_and_provenance_are_merged_for_same_isbn(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {"items": [{
                    "volumeInfo": {
                        "title": "Complementary",
                        "authors": ["Author"],
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780143424123"}],
                        "publishedDate": "2020",
                        "language": "en",
                    },
                }]},
            ),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(
                200,
                {
                    "title": "Complementary",
                    "isbn_13": ["9780143424123"],
                    "publish_date": "2020",
                    "description": "Description from Open Library",
                    "number_of_pages": 240,
                    "authors": [],
                },
            ),
        },
    )

    result = (await providers.search_metadata(isbn="9780143424123"))[0]

    assert result["description"] == "Description from Open Library"
    assert result["page_count"] == 240
    assert result["field_provenance"]["description"] == ["Open Library"]
    assert set(result["field_provenance"]["title"]) == {"Google Books", "Open Library"}


@pytest.mark.asyncio
async def test_conflicting_language_and_edition_values_are_preserved(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {"items": [{
                    "volumeInfo": {
                        "title": "Conflict",
                        "authors": ["Author"],
                        "language": "en",
                        "edition": "1st",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780143424123"}],
                    },
                }]},
            ),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(
                200,
                {
                    "title": "Conflict",
                    "isbn_13": ["9780143424123"],
                    "languages": [{"key": "/languages/fr"}],
                    "edition_name": "2nd",
                    "authors": [],
                },
            ),
        },
    )

    result = (await providers.search_metadata(isbn="9780143424123"))[0]

    assert result["language"] == "en"
    assert result["edition"] == "1st"
    assert set(result["field_conflicts"]["language"]) == {"en", "fr"}
    assert set(result["field_conflicts"]["edition"]) == {"1st", "2nd"}


@pytest.mark.asyncio
async def test_missing_fields_remain_empty_without_invention(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200, {"items": [{"volumeInfo": {"title": "Sparse"}}]}
            ),
            "https://openlibrary.org/search.json": FakeResponse(
                200, {"docs": [{"title": "Sparse"}]}
            ),
        },
    )

    result = (await providers.search_metadata(title="Sparse"))[0]

    assert result["description"] is None
    assert result["edition"] is None
    assert result["price"] is None
    assert result["field_provenance"].keys() == {"title"}


def exact_google_payload(title="Fixture Exact", isbn="9780143424123"):
    return {
        "items": [{
            "volumeInfo": {
                "title": title,
                "authors": ["Fixture Author"],
                "publisher": "Fixture Publisher",
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}],
            }
        }]
    }


def exact_open_library_payload(title="Fixture Exact", isbn="9780143424123"):
    return {
        "title": title,
        "publishers": ["Fixture Publisher"],
        "isbn_13": [isbn],
        "authors": [],
    }


@pytest.mark.asyncio
async def test_google_rate_limit_does_not_block_open_library_exact_isbn(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(429, {}),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(
                200, exact_open_library_payload()
            ),
        },
    )

    results = await providers.search_metadata(isbn="978-0-14-342412-3")

    assert results.result_status == "exact_match"
    assert results.provider_status["Google Books"] == "rate_limited"
    assert results[0]["match_status"] == "exact_isbn"
    assert results[0]["isbn"] == "9780143424123"


@pytest.mark.asyncio
async def test_open_library_timeout_does_not_block_google_exact_isbn(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200, exact_google_payload()
            ),
            "https://openlibrary.org/isbn/9780143424123.json": httpx.ConnectTimeout(
                "timed out"
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results.result_status == "exact_match"
    assert results[0]["source"] == "Google Books"
    assert results[0]["match_status"] == "exact_isbn"


@pytest.mark.asyncio
async def test_both_providers_unavailable_are_reported(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": httpx.ConnectTimeout(
                "timed out"
            ),
            "https://openlibrary.org/isbn/9780143424123.json": httpx.ConnectTimeout(
                "timed out"
            ),
            "https://openlibrary.org/search.json": httpx.ConnectTimeout("timed out"),
            providers.LOC_SRU_URL: httpx.ConnectTimeout("timed out"),
            providers.INTERNET_ARCHIVE_SEARCH_URL: httpx.ConnectTimeout("timed out"),
            providers.WIKIDATA_SPARQL_URL: httpx.ConnectTimeout("timed out"),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results == []
    assert results.result_status == "provider_unavailable"
    assert results.provider_status == {
        "Google Books": "unavailable",
        "Open Library": "unavailable",
        "Library of Congress": "unavailable",
        "Internet Archive": "unavailable",
        "Wikidata": "unavailable",
        "Google Web Discovery": "no_match",
    }


@pytest.mark.asyncio
async def test_wrong_isbn_from_search_fallback_is_rejected(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(429, {}),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(404, {}),
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {
                    "docs": [{
                        "title": "Wrong Edition",
                        "isbn": ["9780306406157"],
                    }]
                },
            ),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results == []
    assert results.result_status == "no_match_found"


@pytest.mark.asyncio
async def test_conflicting_titles_with_same_isbn_are_not_merged(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {
                    "items": [
                        exact_google_payload("Title One")["items"][0],
                        exact_google_payload("Title Two")["items"][0],
                    ]
                },
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(404, {}),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert len(results) == 2
    assert results.result_status == "conflicting_exact_matches"
    assert {candidate["title"] for candidate in results} == {"Title One", "Title Two"}


@pytest.mark.asyncio
async def test_incomplete_isbn_search_fallback_is_not_exact_match(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(429, {}),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(404, {}),
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {"docs": [{"title": "Unverified Search Result"}]},
            ),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results == []
    assert results.result_status == "no_match_found"


@pytest.mark.asyncio
async def test_exact_fixture_isbn_is_classified_and_preserves_provenance(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200, exact_google_payload()
            ),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(
                200, exact_open_library_payload()
            ),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results.result_status == "exact_match"
    assert results[0]["match_status"] == "exact_isbn"
    assert "Google Books" in results[0]["source"]
    assert "Open Library" in results[0]["source"]


LOC_MODS_RESPONSE = """\
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <records><record><recordData>
    <mods xmlns="http://www.loc.gov/mods/v3">
      <titleInfo><title>Fixture Exact</title></titleInfo>
      <name><namePart>Fixture Author</namePart></name>
      <originInfo><publisher>Fixture Publisher</publisher><dateIssued>2020</dateIssued></originInfo>
      <identifier type="isbn">9780143424123</identifier>
      <physicalDescription><extent>200 p.</extent></physicalDescription>
    </mods>
  </recordData></record></records>
</searchRetrieveResponse>
"""


@pytest.mark.asyncio
async def test_new_providers_return_normalized_exact_isbn_candidates(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(429, {}),
            "https://openlibrary.org/isbn/9780143424123.json": FakeResponse(404, {}),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
            providers.LOC_SRU_URL: FakeResponse(200, LOC_MODS_RESPONSE),
            providers.INTERNET_ARCHIVE_SEARCH_URL: FakeResponse(
                200,
                {"response": {"docs": [{
                    "identifier": "fixture-item",
                    "title": "Fixture Exact",
                    "creator": "Fixture Author",
                    "publisher": "Fixture Publisher",
                    "date": "2020",
                    "isbn": ["9780143424123"],
                }]}},
            ),
            providers.WIKIDATA_SPARQL_URL: wikidata_fixture_response,
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert len(results) == 1
    assert results.result_status == "exact_match"
    assert results[0]["match_status"] == "exact_isbn"
    assert {
        "Library of Congress",
        "Internet Archive",
        "Wikidata",
    }.issubset(set(results[0]["source"].split(", ")))
    assert results[0]["page_count"] == 200


@pytest.mark.asyncio
async def test_new_provider_failure_does_not_block_existing_provider(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200, exact_google_payload()
            ),
            "https://openlibrary.org/isbn/9780143424123.json": httpx.TimeoutException(
                "timed out"
            ),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
            providers.LOC_SRU_URL: httpx.TimeoutException("timed out"),
            providers.INTERNET_ARCHIVE_SEARCH_URL: FakeResponse(503, {}),
            providers.WIKIDATA_SPARQL_URL: httpx.ConnectError("unavailable"),
        },
    )

    results = await providers.search_metadata(isbn="9780143424123")

    assert results.result_status == "exact_match"
    assert results[0]["match_status"] == "exact_isbn"
    assert results.provider_status["Library of Congress"] == "unavailable"
    assert results.provider_status["Internet Archive"] == "unavailable"
    assert results.provider_status["Wikidata"] == "unavailable"


@pytest.mark.asyncio
async def test_new_provider_search_results_without_isbn_are_unverified(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(200, {"items": []}),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
            providers.LOC_SRU_URL: FakeResponse(200, LOC_MODS_RESPONSE.replace(
                "9780143424123", ""
            )),
            providers.INTERNET_ARCHIVE_SEARCH_URL: FakeResponse(
                200,
                {"response": {"docs": [{
                    "title": "Fixture Search",
                    "creator": "Fixture Author",
                }]}},
            ),
            providers.WIKIDATA_SPARQL_URL: wikidata_fixture_response,
        },
    )

    results = await providers.search_metadata(title="Fixture Search")

    assert results
    assert all(candidate["match_status"] == "unverified_search" for candidate in results)


def test_author_name_is_not_accepted_as_publisher():
    candidate = providers.normalize_candidate(
        title="A Book",
        author="A. Author",
        publisher="A. Author",
        source="Fixture",
    )
    assert candidate["publisher"] is None


@pytest.mark.asyncio
async def test_missing_authors_do_not_merge_distinct_no_isbn_records(monkeypatch):
    async def fake_google(*args, **kwargs):
        return [
            providers.normalize_candidate(title="Same Title", publisher="Press A", source="Google Books"),
            providers.normalize_candidate(title="Same Title", publisher="Press B", source="Google Books"),
        ]

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(providers, "query_google_books", fake_google)
    monkeypatch.setattr(providers, "query_open_library", empty)
    monkeypatch.setattr(providers, "query_library_of_congress", empty)
    monkeypatch.setattr(providers, "query_internet_archive", empty)
    monkeypatch.setattr(providers, "query_wikidata", empty)

    results = await providers.search_metadata(title="Same Title")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_same_isbn_with_incompatible_titles_remains_separate(monkeypatch):
    isbn = "9780143424123"

    async def fake_google(*args, **kwargs):
        return [
            providers.normalize_candidate(title="Expected Title", author="Author", isbn=isbn, source="Google Books"),
            providers.normalize_candidate(title="Wrong Title", author="Author", isbn=isbn, source="Google Books"),
        ]

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(providers, "query_google_books", fake_google)
    monkeypatch.setattr(providers, "query_open_library", empty)
    monkeypatch.setattr(providers, "query_library_of_congress", empty)
    monkeypatch.setattr(providers, "query_internet_archive", empty)
    monkeypatch.setattr(providers, "query_wikidata", empty)

    results = await providers.search_metadata(isbn=isbn)
    assert {candidate["title"] for candidate in results} == {"Expected Title", "Wrong Title"}
    assert all(candidate["match_status"] == "exact_isbn" for candidate in results)


@pytest.mark.asyncio
async def test_google_title_search_uses_normalized_variants_and_known_publisher(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(
                200,
                {"items": [{"id": "1", "volumeInfo": {"title": "Ikigai", "authors": ["Hector Garcia"], "publisher": "Penguin"}}]},
            )
        },
    )

    await providers.query_google_books(
        FakeAsyncClient(),
        title="Ikigai: The Japanese Secret to a Long and Happy Life",
        author="Hector Garcia",
        publisher="Penguin",
    )

    queries = [params["q"] for url, params in FakeAsyncClient.calls if "googleapis" in url]
    assert len(queries) >= 2
    assert any('intitle:"Ikigai"' in query for query in queries)
    assert all('inauthor:"Hector Garcia"' in query for query in queries)
    assert all('inpublisher:"Penguin"' in query for query in queries)


@pytest.mark.asyncio
async def test_open_library_title_search_enriches_missing_publisher_from_edition(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {"docs": [{"key": "/works/OL1W", "title": "Wings of Fire", "author_name": ["A. P. J. Abdul Kalam"]}]},
            ),
            "https://openlibrary.org/works/OL1W/editions.json": FakeResponse(
                200,
                {"entries": [{"title": "Wings of Fire", "publishers": ["Universities Press"]}]},
            ),
        },
    )

    results = await providers.query_open_library(
        FakeAsyncClient(), title="Wings of Fire", author="A. P. J. Abdul Kalam"
    )

    assert results[0]["publisher"] == "Universities Press"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "author"),
    [
        ("Wings of Fire", "A. P. J. Abdul Kalam"),
        ("Ikigai", "Héctor García, Francesc Miralles"),
        ("A Brief History of Time", "Stephen Hawking"),
        ("The Alchemist", "Paulo Coelho"),
        ("Crime and Punishment", "Fyodor Dostoevsky"),
        ("ആടുജീവിതം", "ബെന്യാമിൻ"),
        ("ഖസാക്കിന്റെ ഇതിഹാസം", "ഒ. വി. വിജയൻ"),
        ("ഇന്ദുലേഖ", "ഒ. ചന്തുമേനോൻ"),
    ],
)
async def test_requested_title_cases_keep_exact_unicode_title_and_author(monkeypatch, title, author):
    async def fake_google(*args, **kwargs):
        return [providers.normalize_candidate(title=title, author=author, source="Google Books")]

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(providers, "query_google_books", fake_google)
    monkeypatch.setattr(providers, "query_open_library", empty)
    monkeypatch.setattr(providers, "query_library_of_congress", empty)
    monkeypatch.setattr(providers, "query_internet_archive", empty)
    monkeypatch.setattr(providers, "query_wikidata", empty)

    results = await providers.search_metadata(title=title, author=author)

    assert results[0]["title"] == title
    assert results[0]["author"] == author
    assert results[0]["publisher"] is None


@pytest.mark.asyncio
async def test_provider_requests_include_descriptive_user_agent(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            providers.WIKIDATA_SPARQL_URL: FakeResponse(200, {"results": {"bindings": []}}),
            "https://openlibrary.org/search.json": FakeResponse(200, {"docs": []}),
        },
    )
    client = FakeAsyncClient()

    await providers.query_wikidata(client, title="Ikigai")
    await providers.query_open_library(client, title="Ikigai")

    relevant = [details for url, _, details in client.call_details if "wikidata" in url or "openlibrary" in url]
    assert "https://" in providers.USER_AGENT or "@" in providers.USER_AGENT
    assert relevant
    assert all(details["headers"]["User-Agent"] == providers.USER_AGENT for details in relevant)


@pytest.mark.asyncio
async def test_google_books_api_key_and_first_rate_limit_short_circuit(monkeypatch):
    calls = []

    def response(url, params):
        calls.append(params)
        return FakeResponse(429, {})

    install_fake_client(monkeypatch, {"https://www.googleapis.com/books/v1/volumes": response})
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")

    status = {}
    results = await providers.query_google_books(
        FakeAsyncClient(), title="Ikigai: The Japanese Secret to a Long and Happy Life", status=status
    )

    assert results == []
    assert status["Google Books"] == "rate_limited"
    assert len(calls) == 1
    assert calls[0]["key"] == "test-key"


@pytest.mark.asyncio
async def test_internet_archive_restricts_to_texts_and_filters_audio_junk(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            providers.INTERNET_ARCHIVE_SEARCH_URL: FakeResponse(
                200,
                {"response": {"docs": [{"title": "[Sách nói] Ikigai - Hector Garcia | AudioHay.net"}]}},
            )
        },
    )

    client = FakeAsyncClient()
    results = await providers.query_internet_archive(client, title="Ikigai", author="Hector Garcia")

    assert results == []
    archive_call = next(params for url, params in client.calls if "archive.org" in url)
    assert "mediatype:texts" in archive_call["q"]


@pytest.mark.asyncio
async def test_open_library_malayalam_search_is_bounded_and_uses_unicode_params(monkeypatch):
    install_fake_client(
        monkeypatch,
        {
            "https://openlibrary.org/search.json": FakeResponse(
                200,
                {"docs": [{"key": f"/works/OL{i}W", "title": "ആടുജീവിതം", "author_name": ["ബെന്യാമിൻ"]} for i in range(5)]},
            ),
            "https://openlibrary.org/works/OL0W/editions.json": FakeResponse(200, {"entries": []}),
            "https://openlibrary.org/works/OL1W/editions.json": FakeResponse(200, {"entries": []}),
        },
    )
    client = FakeAsyncClient()

    await providers.query_open_library(client, title="ആടുജീവിതം", author="ബെന്യാമിൻ")

    search_calls = [(url, params) for url, params in client.calls if url.endswith("/search.json")]
    edition_calls = [url for url, _ in client.calls if url.endswith("/editions.json")]
    assert len(search_calls) == 2
    assert len(edition_calls) == 2
    assert search_calls[0][1]["title"] == "ആടുജീവിതം"
    assert search_calls[1][1]["title"] != "ആടുജീവിതം"


@pytest.mark.asyncio
async def test_exact_standalone_title_outranks_omnibus_and_adaptation(monkeypatch):
    async def fake_google(*args, **kwargs):
        return [
            providers.normalize_candidate(title="The Alchemist - The Pilgrimage - By the River Piedra I Sat Down and Wept", author="Paulo Coelho", source="Google Books"),
            providers.normalize_candidate(title="The Alchemist Graphic Novel", author="Paulo Coelho", source="Google Books"),
            providers.normalize_candidate(title="The Alchemist", author="Paulo Coelho", publisher="HarperCollins", source="Google Books"),
        ]

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(providers, "query_google_books", fake_google)
    monkeypatch.setattr(providers, "query_open_library", empty)
    monkeypatch.setattr(providers, "query_library_of_congress", empty)
    monkeypatch.setattr(providers, "query_internet_archive", empty)
    monkeypatch.setattr(providers, "query_wikidata", empty)

    results = await providers.search_metadata(title="The Alchemist", author="Paulo Coelho")

    assert results[0]["title"] == "The Alchemist"
    assert all("Graphic Novel" not in result["title"] for result in results)


@pytest.mark.asyncio
async def test_required_isbn_lookup_remains_exact(monkeypatch):
    isbn = "9780140449136"
    install_fake_client(
        monkeypatch,
        {
            "https://www.googleapis.com/books/v1/volumes": FakeResponse(200, exact_google_payload(isbn=isbn)),
            "https://openlibrary.org/isbn/9780140449136.json": FakeResponse(404, {}),
        },
    )

    results = await providers.search_metadata(isbn=isbn)

    assert results
    assert results[0]["isbn"] == isbn
    assert results[0]["match_status"] == "exact_isbn"


@pytest.mark.asyncio
async def test_wikidata_mediawiki_api_returns_english_book_metadata(monkeypatch):
    def response(url, params):
        if params["action"] == "wbsearchentities":
            return FakeResponse(200, {"search": [{"id": "Q10"}]})
        if params.get("props") == "labels":
            return FakeResponse(200, {"entities": {
                "Q20": {"labels": {"en": {"value": "Stephen Hawking"}}},
                "Q30": {"labels": {"en": {"value": "Bantam Books"}}},
            }})
        return FakeResponse(200, {"entities": {"Q10": {
            "labels": {"en": {"value": "A Brief History of Time"}},
            "claims": {
                "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}],
                "P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q20"}}}}],
                "P123": [{"mainsnak": {"datavalue": {"value": {"id": "Q30"}}}}],
            },
        }}})

    install_fake_client(monkeypatch, {providers.WIKIDATA_API_URL: response})
    client = FakeAsyncClient()
    results = await providers.query_wikidata(client, title="A Brief History of Time")

    assert results[0]["title"] == "A Brief History of Time"
    assert results[0]["author"] == "Stephen Hawking"
    assert results[0]["publisher"] == "Bantam Books"
    assert all(params["action"] in {"wbsearchentities", "wbgetentities"} for _, params in client.calls)


@pytest.mark.asyncio
async def test_wikidata_mediawiki_api_uses_malayalam_search_language(monkeypatch):
    def response(url, params):
        if params["action"] == "wbsearchentities":
            assert params["language"] == "ml"
            assert params["uselang"] == "ml"
            return FakeResponse(200, {"search": [{"id": "Q11"}]})
        if params.get("props") == "labels":
            return FakeResponse(200, {"entities": {
                "Q21": {"labels": {"ml": {"value": "ബെന്യാമിൻ"}}},
            }})
        return FakeResponse(200, {"entities": {"Q11": {
            "labels": {"ml": {"value": "ആടുജീവിതം"}},
            "claims": {
                "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}],
                "P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q21"}}}}],
            },
        }}})

    install_fake_client(monkeypatch, {providers.WIKIDATA_API_URL: response})
    results = await providers.query_wikidata(FakeAsyncClient(), title="ആടുജീവിതം")

    assert results[0]["title"] == "ആടുജീവിതം"
    assert results[0]["author"] == "ബെന്യാമിൻ"
    assert results[0]["publisher"] is None


@pytest.mark.asyncio
async def test_open_library_empty_docs_is_no_match(monkeypatch):
    install_fake_client(
        monkeypatch,
        {"https://openlibrary.org/search.json": FakeResponse(200, {"docs": []})},
    )
    status = {}
    results = await providers.query_open_library(
        FakeAsyncClient(), title="ആടുജീവിതം", status=status
    )

    assert results == []
    assert status["Open Library"] == "no_match"


def test_normalize_author_name_inverted_and_trailing_commas():
    assert providers.normalize_author_name("Clear, James,") == "James Clear"
    assert providers.normalize_author_name("Todd, Charles.") == "Charles Todd"
    assert providers.normalize_author_name("Brown, Dale,, 1956-") == "Dale Brown"
    assert providers.normalize_author_name("Dostoievski, Fiódor, 1821-1881.") == "Fiódor Dostoievski"
    assert providers.normalize_author_name("Kalam, A. P. J. Abdul") == "A. P. J. Abdul Kalam"
    assert providers.normalize_author_name("Clarke, Arthur C.") == "Arthur C. Clarke"
    assert providers.normalize_author_name("King, Martin Luther, Jr.") == "Martin Luther King, Jr."


def test_normalize_authors_multi_author_and_preservation():
    assert providers.normalize_authors(["García, Héctor,", "Miralles, Francesc,"]) == "Héctor García, Francesc Miralles"
    assert providers.normalize_authors("Héctor García, Francesc Miralles") == "Héctor García, Francesc Miralles"
    assert providers.normalize_authors("Tui T. Sutherland, Kari Sutherland") == "Tui T. Sutherland, Kari Sutherland"
    assert providers.normalize_authors("Todd, Charles; Todd, Caroline") == "Charles Todd, Caroline Todd"
    assert providers.normalize_authors("Todd, Charles; Todd, Charles") == "Charles Todd"


def test_normalize_authors_protects_malayalam():
    assert providers.normalize_authors("ഒ. ചന്തുമേനോൻ") == "ഒ. ചന്തുമേനോൻ"
    assert providers.normalize_authors("ഒ.വി. വിജയൻ, ഡി.സി. ബുക്സ്") == "ഒ.വി. വിജയൻ, ഡി.സി. ബുക്സ്"
    assert providers.normalize_authors("ഒ. ചന്തുമേനോൻ,") == "ഒ. ചന്തുമേനോൻ"


def test_normalize_candidate_cleans_author_automatically():
    cand = providers.normalize_candidate("Test Book", author="Clear, James,")
    assert cand["author"] == "James Clear"


@pytest.mark.asyncio
async def test_library_of_congress_author_cleaning_with_date_and_inverted_name(monkeypatch):
    loc_xml = """\
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <records><record><recordData>
    <mods xmlns="http://www.loc.gov/mods/v3">
      <titleInfo><title>Flight of the Old Dog</title></titleInfo>
      <name type="personal">
        <namePart>Brown, Dale,</namePart>
        <namePart type="date">1956-</namePart>
      </name>
      <originInfo><publisher>Putnam</publisher><dateIssued>1987</dateIssued></originInfo>
      <identifier type="isbn">9780399132278</identifier>
    </mods>
  </recordData></record></records>
</searchRetrieveResponse>
"""
    install_fake_client(monkeypatch, {providers.LOC_SRU_URL: FakeResponse(200, loc_xml)})
    results = await providers.query_library_of_congress(FakeAsyncClient(), isbn="9780399132278")

    assert len(results) == 1
    assert results[0]["title"] == "Flight of the Old Dog"
    assert results[0]["author"] == "Dale Brown"

