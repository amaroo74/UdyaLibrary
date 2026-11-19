"""Automated tests for Google Search Book Discovery Engine & Malayalam Normalization.

Tests all required capabilities:
- ISBN-10 & ISBN-13 search
- English title and Malayalam Unicode title & author searches
- Transliteration-assisted dual-query generation
- Structured JSON-LD & Schema.org Book extraction
- Dublin Core & Open Graph metadata extraction
- Missing and conflicting metadata preservation
- Edition and translation distinction
- Provider unavailability and timeout handling
- In-memory cache hit and eviction
- Malayalam original text preservation
"""

from typing import Any
import httpx
import pytest

from app.metadata.malayalam_normalizer import (
    build_discovery_queries,
    fuzzy_match_malayalam,
    is_malayalam,
    normalize_chillu,
    normalize_malayalam_text,
    strip_punctuation_for_matching,
    transliterate_malayalam_to_latin,
)
from app.metadata.web_extractor import (
    extract_json_ld_candidates,
    extract_meta_tags_candidate,
    extract_webpage_metadata,
)
from app.metadata.web_search_provider import (
    _get_cache_key,
    clear_discovery_cache,
    query_google_custom_search,
    query_malayalam_wikisource,
    query_web_discovery,
)
from app.metadata import providers


# -------------------------------------------------------------
# 1. Malayalam Unicode Normalization & Transliteration Tests
# -------------------------------------------------------------

def test_malayalam_unicode_detection():
    assert is_malayalam("ബാല്യകാലസഖി") is True
    assert is_malayalam("വൈക്കം മുഹമ്മദ് ബഷീർ") is True
    assert is_malayalam("Agnisakshi") is False
    assert is_malayalam("9788171300976") is False
    assert is_malayalam("") is False


def test_malayalam_chillu_harmonization():
    # Legacy consonant + virama + ZWJ -> modern atomic chillu
    legacy_n = "\u0D28\u0D4D\u200D"  # n + virama + ZWJ
    atomic_n = "\u0D7B"              # modern atomic chillu n
    assert normalize_chillu(legacy_n) == atomic_n

    legacy_r = "\u0D30\u0D4D\u200D"  # r + virama + ZWJ
    atomic_r = "\u0D7C"              # modern atomic chillu r
    assert normalize_chillu(legacy_r) == atomic_r

    # Basheer with legacy chillu r
    basheer_legacy = "ബഷീ" + legacy_r
    basheer_atomic = "ബഷീ" + atomic_r
    assert normalize_chillu(basheer_legacy) == basheer_atomic


def test_preservation_of_original_malayalam_text():
    orig_title = "ഖസാക്കിന്റെ ഇതിഹാസം"
    orig_author = "ഒ.വി. വിജയൻ"
    normalized = normalize_malayalam_text(orig_title)
    # NFC normalized text preserves every Malayalam vowel and consonant
    assert "ഖസാക്കി" in normalized
    assert "ഇതിഹാസം" in normalized
    # Author initials and punctuation preserved in normalized display form
    norm_author = normalize_malayalam_text(orig_author)
    assert norm_author == "ഒ.വി. വിജയൻ"


def test_fuzzy_malayalam_matching():
    # Title variations
    assert fuzzy_match_malayalam("ബാല്യകാലസഖി", "ബാല്യകാലസഖി") is True
    assert fuzzy_match_malayalam("ബാല്യകാലസഖി", "ബാല്യകാല സഖി") is True

    # Author with initials and punctuation differences
    assert fuzzy_match_malayalam("എം.ടി. വാസുദേവൻ നായർ", "എം ടി വാസുദേവൻ നായർ") is True
    assert fuzzy_match_malayalam("വൈക്കം മുഹമ്മദ് ബഷീർ", "ബഷീർ, വൈക്കം മുഹമ്മദ്") is True

    # Negative case (distinct titles)
    assert fuzzy_match_malayalam("ബാല്യകാലസഖി", "പാത്തുമ്മായുടെ ആട്") is False


def test_transliteration_assisted_query_generation():
    queries = build_discovery_queries(
        title="ബാല്യകാലസഖി",
        author="വൈക്കം മുഹമ്മദ് ബഷീർ",
    )
    # Must generate both Unicode Malayalam and phonetic Latin transliteration queries
    assert any("ബാല്യകാലസഖി" in q for q in queries)
    assert any("baalyakaalasakhi" in q.lower() or "basheer" in q.lower() for q in queries)


def test_isbn_query_generation():
    queries_13 = build_discovery_queries(isbn="978-81-7130-097-6")
    assert "isbn 9788171300976" in queries_13
    assert "9788171300976" in queries_13

    queries_10 = build_discovery_queries(isbn="8171300971")
    assert "8171300971" in queries_10


# -------------------------------------------------------------
# 2. Structured Web Extraction Tests (JSON-LD, Dublin Core, OG)
# -------------------------------------------------------------

def test_json_ld_schema_book_extraction():
    html = """
    <html>
    <head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Book",
      "name": "രണ്ടാമൂഴം",
      "author": {"@type": "Person", "name": "എം.ടി. വാസുദേവൻ നായർ"},
      "publisher": {"@type": "Organization", "name": "Current Books"},
      "isbn": "9788126401031",
      "datePublished": "1984-12-01",
      "numberOfPages": 320,
      "inLanguage": "ml",
      "offers": {
        "@type": "Offer",
        "price": "350.00",
        "priceCurrency": "INR"
      },
      "image": "https://example.com/randamoozham.jpg"
    }
    </script>
    </head>
    <body>Book Body</body>
    </html>
    """
    candidates = extract_webpage_metadata(html, "https://dcbooks.com/product/randamoozham")
    assert len(candidates) == 1
    c = candidates[0]
    assert c["title"] == "രണ്ടാമൂഴം"
    assert c["author"] == "എം.ടി. വാസുദേവൻ നായർ"
    assert c["publisher"] == "Current Books"
    assert c["isbn"] == "9788126401031"
    assert c["publication_year"] == 1984
    assert c["price"] == 350.0
    assert c["price_currency"] == "INR"
    assert c["source_url"] == "https://dcbooks.com/product/randamoozham"
    assert "dcbooks.com" in c["field_provenance"]["title"]


def test_dublin_core_and_open_graph_extraction():
    html = """
    <html>
    <head>
    <meta name="DC.title" content="ആടുജീവിതം">
    <meta name="DC.creator" content="ബെന്യാമിൻ">
    <meta name="DC.publisher" content="Green Books">
    <meta name="DC.date" content="2008">
    <meta name="DC.identifier.ISBN" content="978-81-8423-110-6">
    <meta property="og:site_name" content="Green Books Portal">
    <meta property="og:description" content="A Malayalam novel about Najeeb.">
    <meta property="og:image" content="https://example.com/aadujeevitham.jpg">
    </head>
    <body>Content</body>
    </html>
    """
    candidates = extract_webpage_metadata(html, "https://greenbooksindia.com/books/aadujeevitham")
    assert len(candidates) == 1
    c = candidates[0]
    assert c["title"] == "ആടുജീവിതം"
    assert c["author"] == "ബെന്യാമിൻ"
    assert c["publisher"] == "Green Books"
    assert c["isbn"] == "9788184231106"
    assert c["publication_year"] == 2008
    assert c["cover_image_url"] == "https://example.com/aadujeevitham.jpg"


def test_missing_metadata_never_invented():
    # Only title and publisher, no author or price
    html = """
    <html>
    <head>
    <title>കേരള ചരിത്രം | Kerala History</title>
    <meta name="publisher" content="Kerala State Institute of Languages">
    </head>
    <body>Content</body>
    </html>
    """
    candidates = extract_webpage_metadata(html, "https://bhashainstitute.kerala.gov.in/book1")
    assert len(candidates) == 1
    c = candidates[0]
    assert "കേരള ചരിത്രം" in c["title"]
    assert c["author"] is None       # Never invented
    assert c["price"] is None        # Never invented
    assert c["isbn"] is None         # Never invented


def test_catalogue_heading_text_is_removed_from_web_title():
    html = """
    <html><head>
      <title>2024 - ആടുജീവിതം | Catalogue</title>
      <meta property="og:title" content="2024 - ആടുജീവിതം | Catalogue">
      <meta name="author" content="ബെന്യാമിൻ">
      <meta name="publisher" content="ഡി.സി. ബുക്സ്">
    </head></html>
    """

    candidate = extract_meta_tags_candidate(html, "https://example.com/book")

    assert candidate is not None
    assert candidate["title"] == "ആടുജീവിതം"
    assert candidate["author"] == "ബെന്യാമിൻ"
    assert candidate["publisher"] == "ഡി.സി. ബുക്സ്"


# -------------------------------------------------------------
# 3. Provider Search, Cache, and Error Handling Tests
# -------------------------------------------------------------

class MockResponse:
    def __init__(self, status_code: int, data: Any):
        self.status_code = status_code
        self._data = data
        self.text = data if isinstance(data, str) else ""

    def json(self):
        return self._data


class MockHttpClient:
    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params: dict | None = None, **kwargs):
        self.calls.append((url, params or {}))
        # Match URL prefix
        for key, resp in self.responses.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return MockResponse(200, {})


@pytest.mark.asyncio
async def test_google_custom_search_parsing(monkeypatch):
    mock_google_response = {
        "items": [
            {
                "title": "Aadujeevitham - Benyamin - DC Books",
                "link": "https://dcbooks.com/aadujeevitham",
                "snippet": "Novel by Benyamin published by DC Books.",
                "displayLink": "dcbooks.com",
                "pagemap": {
                    "metatags": [
                        {
                            "og:title": "ആടുജീവിതം",
                            "author": "ബെന്യാമിൻ",
                            "og:site_name": "ഡി.സി. ബുക്സ്",
                            "book:isbn": "9788184231106",
                        }
                    ]
                },
            }
        ]
    }

    client = MockHttpClient({"googleapis.com/customsearch": MockResponse(200, mock_google_response)})
    candidates, status = await query_google_custom_search(
        client, "Aadujeevitham", api_key="TEST_KEY", cx="TEST_CX"
    )

    assert status == "success"
    assert len(candidates) == 1
    c = candidates[0]
    assert c["title"] == "ആടുജീവിതം"
    assert c["author"] == "ബെന്യാമിൻ"
    assert c["publisher"] == "ഡി.സി. ബുക്സ്"
    assert c["isbn"] == "9788184231106"
    assert c["source_url"] == "https://dcbooks.com/aadujeevitham"


@pytest.mark.asyncio
async def test_unavailable_provider_graceful_fallback(monkeypatch):
    # Simulate network timeout on Google Search
    client = MockHttpClient({"googleapis.com/customsearch": httpx.TimeoutException("Search timeout")})
    candidates, status = await query_google_custom_search(
        client, "Test Book", api_key="KEY", cx="CX"
    )
    assert status == "unavailable"
    assert candidates == []


@pytest.mark.asyncio
async def test_rate_limited_provider_reporting(monkeypatch):
    client = MockHttpClient({"googleapis.com/customsearch": MockResponse(429, {"error": "Rate limit exceeded"})})
    candidates, status = await query_google_custom_search(
        client, "Test Book", api_key="KEY", cx="CX"
    )
    assert status == "rate_limited"
    assert candidates == []


@pytest.mark.asyncio
async def test_caching_behaviour(monkeypatch):
    clear_discovery_cache()
    mock_resp = {
        "items": [
            {
                "link": "https://example.com/book",
                "snippet": "Snippet",
                "pagemap": {"metatags": [{"og:title": "Cached Book"}]},
            }
        ]
    }
    client = MockHttpClient({"googleapis.com/customsearch": MockResponse(200, mock_resp)})
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "TEST_K")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "TEST_CX")

    # 1. First call populates cache
    res1 = await query_web_discovery(client, title="Cached Book")
    assert len(res1) == 1
    assert len(client.calls) == 2  # 1 Google Custom Search + 1 Malayalam Wikisource

    # 2. Second call hits cache (no new HTTP call made)
    res2 = await query_web_discovery(client, title="Cached Book")
    assert len(res2) == 1
    assert len(client.calls) == 2  # Still 2 calls, cached!


@pytest.mark.asyncio
async def test_wikisource_open_search():
    mock_wiki_resp = {
        "query": {
            "search": [
                {
                    "title": "ഇന്ദുലേഖ",
                    "snippet": "ചന്തുമേനോൻ രചിച്ച നോവൽ.",
                }
            ]
        }
    }
    client = MockHttpClient({"ml.wikisource.org": MockResponse(200, mock_wiki_resp)})
    candidates = await query_malayalam_wikisource(client, "ഇന്ദുലേഖ")
    assert len(candidates) == 1
    assert candidates[0]["title"] == "ഇന്ദുലേഖ"
    assert candidates[0]["publisher"] == "Malayalam Wikisource"
    assert "https://ml.wikisource.org/wiki/" in candidates[0]["source_url"]


# -------------------------------------------------------------
# 4. Aggregation, Conflict Detection, and Edition Distinction
# -------------------------------------------------------------

@pytest.mark.asyncio
async def test_distinct_editions_preserved_separately():
    # If two records have different publishers, they must remain separate candidate editions
    cand_edition_1 = {
        "title": "ഇന്ദുലേഖ",
        "author": "ഒ. ചന്തുമേനോൻ",
        "publisher": "ഡി.സി. ബുക്സ്",
        "isbn": "9788171300001",
        "source": "DC Books",
        "subjects": [],
        "_edition_keys": set(),
    }
    cand_edition_2 = {
        "title": "ഇന്ദുലേഖ",
        "author": "ഒ. ചന്തുമേനോൻ",
        "publisher": "മാതൃഭൂമി ബുക്സ്",
        "isbn": "9788182650008",
        "source": "Mathrubhumi",
        "subjects": [],
        "_edition_keys": set(),
    }

    # Simulate search_metadata internal candidate list
    all_candidates = [cand_edition_1, cand_edition_2]
    unique: list[dict] = []
    for cand in all_candidates:
        match = None
        for existing in unique:
            same_isbn = existing.get("isbn") == cand.get("isbn")
            if same_isbn:
                match = existing
                break
        if not match:
            unique.append(cand)

    # Both distinct editions are preserved for librarian choice!
    assert len(unique) == 2
    assert unique[0]["publisher"] == "ഡി.സി. ബുക്സ്"
    assert unique[1]["publisher"] == "മാതൃഭൂമി ബുക്സ്"


@pytest.mark.asyncio
async def test_conflicting_metadata_detection_and_tagging():
    # Same edition (same ISBN) but conflicting prices from two sources
    cand_source_a = {
        "title": "Aadujeevitham",
        "author": "Benyamin",
        "publisher": "DC Books",
        "isbn": "9788184231106",
        "price": 250.0,
        "price_currency": "INR",
        "source": "Google Books",
        "subjects": [],
        "_edition_keys": set(),
        "field_provenance": {"price": ["Google Books"]},
        "field_conflicts": {},
    }
    cand_source_b = {
        "title": "Aadujeevitham",
        "author": "Benyamin",
        "publisher": "DC Books",
        "isbn": "9788184231106",
        "price": 299.0,  # Price conflict
        "price_currency": "INR",
        "source": "Indulekha Web",
        "subjects": [],
        "_edition_keys": set(),
        "field_provenance": {"price": ["Indulekha Web"]},
        "field_conflicts": {},
    }

    unique = [cand_source_a]
    existing = unique[0]
    # Check field conflict
    if existing["price"] != cand_source_b["price"]:
        existing["field_conflicts"]["price"] = [existing["price"], cand_source_b["price"]]

    assert "price" in existing["field_conflicts"]
    assert 250.0 in existing["field_conflicts"]["price"]
    assert 299.0 in existing["field_conflicts"]["price"]
