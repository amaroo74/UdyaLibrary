"""Online metadata providers and conservative cross-provider enrichment."""

import asyncio
import logging
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any
import httpx
from ..isbn import clean_isbn, normalize_isbn
from .malayalam_normalizer import (
    fuzzy_match_malayalam,
    normalize_malayalam_text,
    strip_punctuation_for_matching,
    transliterate_malayalam_to_latin,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6.0
USER_AGENT = "UdayaLibrary/1.0 (https://github.com/udaya-vayanasala/udaya-library; contact@udayavayanasala.org)"
PROVIDER_HEADERS = {"User-Agent": USER_AGENT}
GOOGLE_BOOKS_API_KEY_ENV = "GOOGLE_BOOKS_API_KEY"
LOC_SRU_URL = "http://lx2.loc.gov:210/LCDB"
INTERNET_ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"


class MetadataSearchResults(list[dict[str, Any]]):
    """List-compatible metadata results with provider and match diagnostics."""

    def __init__(
        self,
        candidates: list[dict[str, Any]] = (),
        *,
        result_status: str = "no_match_found",
        provider_status: dict[str, str] | None = None,
        conflicts: list[str] | None = None,
    ):
        super().__init__(candidates)
        self.result_status = result_status
        self.provider_status = provider_status or {}
        self.conflicts = conflicts or []


def first_text(value: Any) -> str | None:
    """Return the first usable text value from provider list-or-string fields."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def description_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_text(value.get("value"))
    return first_text(value)


def normalize_candidate(
    title: str,
    author: str | None = None,
    publisher: str | None = None,
    price: float | None = None,
    price_source: str | None = None,
    price_currency: str | None = None,
    source: str = "unknown",
    subjects: list[str] | None = None,
    edition_keys: set[str] | None = None,
    published_date: str | None = None,
    publication_year: int | None = None,
    edition: str | None = None,
    language: str | None = None,
    page_count: int | None = None,
    description: str | None = None,
    isbn: str | None = None,
    subtitle: str | None = None,
    editor: str | None = None,
    translator: str | None = None,
    series: str | None = None,
    volume: str | None = None,
    cover_image_url: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Normalize provider data and retain transient bibliographic details."""
    candidate = {
        "title": title.strip() if title else "",
        "author": author.strip() if author else None,
        "publisher": _safe_publisher(publisher, author),
        "price": float(price) if price is not None and price > 0 else None,
        "price_source": price_source if price is not None and price > 0 else None,
        "price_currency": price_currency.strip().upper() if price is not None and price > 0 and price_currency and price_currency.strip() else None,
        "source": source,
        "subjects": list(dict.fromkeys(subjects or [])),
        "published_date": published_date.strip() if published_date else None,
        "publication_year": publication_year,
        "edition": edition.strip() if edition else None,
        "language": language.strip() if language else None,
        "page_count": page_count if isinstance(page_count, int) and page_count > 0 else None,
        "description": description.strip() if description else None,
        "isbn": normalize_isbn(isbn),
        "subtitle": subtitle.strip() if subtitle else None,
        "editor": editor.strip() if editor else None,
        "translator": translator.strip() if translator else None,
        "series": series.strip() if series else None,
        "volume": volume.strip() if volume else None,
        "cover_image_url": cover_image_url.strip() if cover_image_url else None,
        "source_url": source_url.strip() if source_url else None,
        "_edition_keys": edition_keys or set(),
    }
    if source_url is None:
        candidate.pop("source_url")
    candidate["field_provenance"] = {
        field: [source]
        for field in (
            "title", "author", "publisher", "price", "published_date",
            "publication_year", "edition", "language", "page_count",
            "description", "isbn", "subtitle", "editor", "translator",
            "series", "volume", "cover_image_url", "source_url",
        )
        if candidate.get(field) is not None
    }
    candidate["field_conflicts"] = {}
    return candidate


def _xml_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _xml_children(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [
        child
        for child in element.iter()
        if child.tag.rsplit("}", 1)[-1] == local_name
    ]


def _first_xml_text(element: ET.Element, local_name: str) -> str | None:
    for child in _xml_children(element, local_name):
        value = _xml_text(child)
        if value:
            return value
    return None


def _first_isbn(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    return next(
        (normalized for item in values if (normalized := normalize_isbn(item))),
        None,
    )


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(\d{4})\b", value)
    return int(match.group(1)) if match else None


def _match_key(value: str | None) -> str:
    """Create a punctuation/spacing-insensitive key without losing Unicode."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


def _titles_compatible(left: str | None, right: str | None) -> bool:
    left_key = _match_key(left)
    right_key = _match_key(right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or left_key in right_key or right_key in left_key


def _authors_compatible(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_key = _match_key(left)
    right_key = _match_key(right)
    return left_key == right_key or fuzzy_match_malayalam(left, right)


def _safe_publisher(publisher: str | None, author: str | None) -> str | None:
    """Discard a common provider error where the author is copied as publisher."""
    value = publisher.strip() if isinstance(publisher, str) else ""
    if not value:
        return None
    if author:
        author_values = re.split(r"\s*(?:,|;|&|\band\b)\s*", author, flags=re.IGNORECASE)
        author_keys = {_match_key(item) for item in author_values if _match_key(item)}
        if _match_key(value) in author_keys or _match_key(value) == _match_key(author):
            return None
    return value


def _title_variants(title: str | None) -> list[str]:
    """Return conservative title variants while preserving the original display title."""
    if not title:
        return []
    original = normalize_malayalam_text(title)
    punctuation = strip_punctuation_for_matching(original)
    without_subtitle = re.split(r"\s*[:–—-]\s*", original, maxsplit=1)[0].strip()
    variants = [original, punctuation, without_subtitle]
    return list(dict.fromkeys(value for value in variants if value))


def _author_match_rank(requested: str | None, candidate: str | None) -> int:
    if not requested:
        return 0
    if not candidate:
        return 2
    if _match_key(requested) == _match_key(candidate):
        return 0
    if fuzzy_match_malayalam(requested, candidate):
        return 1
    requested_parts = {_match_key(part) for part in re.split(r"\s*(?:,|;|&|\band\b)\s*", requested, flags=re.IGNORECASE)}
    candidate_key = _match_key(candidate)
    if candidate_key and any(part and part in candidate_key for part in requested_parts):
        return 1
    return 3


def _title_match_rank(requested: str | None, candidate: str | None) -> int:
    if not requested or not candidate:
        return 3
    requested_key = _match_key(requested)
    candidate_key = _match_key(candidate)
    if requested_key == candidate_key:
        return 0
    requested_base = _match_key(_title_variants(requested)[-1])
    candidate_base = _match_key(_title_variants(candidate)[-1])
    if requested_base and requested_base == candidate_base:
        return 1
    if _titles_compatible(requested, candidate):
        return 2
    return 3


def _candidate_language_rank(candidate: dict[str, Any], requested_title: str | None) -> int:
    """Prefer the requested script/language while keeping alternatives visible."""
    language = str(candidate.get("language") or "").casefold()
    title = str(candidate.get("title") or "")
    requested_is_malayalam = bool(requested_title and any("\u0d00" <= c <= "\u0d7f" for c in requested_title))
    candidate_is_malayalam = any("\u0d00" <= c <= "\u0d7f" for c in title)
    if requested_is_malayalam:
        return 0 if candidate_is_malayalam or "mal" in language or "ml" in language else 1
    return 0 if not language or language.startswith(("en", "eng")) else 1


JUNK_TITLE_PATTERNS = (
    re.compile(r"\[|\]"),
    re.compile(r"\|"),
    re.compile(r"\b(?:audiobook|audio book|summary|study guide|graphic novel|abridged|illustrated|omnibus)\b", re.IGNORECASE),
    re.compile(r"\b(?:sách\s+nói)\b", re.IGNORECASE),
    re.compile(r"\.(?:com|net|org)\b", re.IGNORECASE),
)


def _is_junk_title(title: str | None, requested_title: str | None) -> bool:
    if not title:
        return False
    title_key = title.casefold()
    requested_key = (requested_title or "").casefold()
    return any(pattern.search(title) and not pattern.search(requested_key) for pattern in JUNK_TITLE_PATTERNS)


def _candidate_quality_penalty(candidate: dict[str, Any], requested_title: str | None) -> int:
    """Penalize foreign-script and non-standalone results without changing display data."""
    title = str(candidate.get("title") or "")
    if not requested_title or any("\u0d00" <= char <= "\u0d7f" for char in requested_title):
        return 0
    if title and any(ord(char) > 127 for char in title):
        return 2
    return 0


async def query_google_books(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query Google Books Volumes API without scraping or requiring an API key."""
    candidates: list[dict[str, Any]] = []
    q_parts = []
    if isbn:
        clean = clean_isbn(isbn)
        q_parts.append(f"isbn:{clean}")
    elif title and author:
        q_parts.append(f'intitle:"{title.strip()}"')
        q_parts.append(f'inauthor:"{author.strip()}"')
    elif title:
        q_parts.append(f'intitle:"{title.strip()}"')
    elif author:
        q_parts.append(f'inauthor:"{author.strip()}"')
    elif query:
        q_parts.append(query.strip())

    if not q_parts:
        if status is not None:
            status["Google Books"] = "no_match"
        return candidates

    url = "https://www.googleapis.com/books/v1/volumes"
    try:
        queries = [" ".join(q_parts)]
        if title and not isbn:
            queries = []
            for variant in _title_variants(title):
                query_parts = [f'intitle:"{variant}"']
                if author:
                    query_parts.append(f'inauthor:"{author.strip()}"')
                if publisher:
                    query_parts.append(f'inpublisher:"{publisher.strip()}"')
                queries.append(" ".join(query_parts))
            if any("\u0d00" <= char <= "\u0d7f" for char in title):
                latin_title = transliterate_malayalam_to_latin(title)
                if latin_title and latin_title != title:
                    queries.append(f'intitle:"{latin_title}"' + (f' inauthor:"{author.strip()}"' if author else ""))

        seen_ids: set[str] = set()
        items: list[dict[str, Any]] = []
        rate_limited = False
        for search_query in queries:
            params = {"q": search_query, "maxResults": 5, "printType": "books"}
            api_key = os.getenv(GOOGLE_BOOKS_API_KEY_ENV, "").strip()
            if api_key:
                params["key"] = api_key
            resp = await client.get(url, params=params, headers=PROVIDER_HEADERS, timeout=TIMEOUT_SECONDS)
            if resp.status_code != 200:
                if status is not None:
                    status["Google Books"] = "rate_limited" if resp.status_code == 429 else "unavailable"
                if resp.status_code == 429:
                    rate_limited = True
                    break
                continue
            data = resp.json()
            for item in (data.get("items", []) if isinstance(data, dict) else []):
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                items.append(item)
        for item in items:
            v_info = item.get("volumeInfo", {})
            b_title = v_info.get("title")
            if not b_title:
                continue

            authors = v_info.get("authors", [])
            author_str = ", ".join(authors) if authors else None
            publisher = v_info.get("publisher")
            edition_keys = {
                f"isbn:{identifier.get('identifier').replace('-', '')}"
                for identifier in v_info.get("industryIdentifiers", [])
                if isinstance(identifier, dict)
                and identifier.get("identifier")
                and identifier.get("type") in {"ISBN_10", "ISBN_13"}
            }
            isbn_values = [
                identifier.get("identifier")
                for identifier in v_info.get("industryIdentifiers", [])
                if isinstance(identifier, dict) and identifier.get("identifier")
            ]
            subjects = [
                subject
                for subject in v_info.get("categories", [])
                if isinstance(subject, str) and subject.strip()
            ]
            page_count = v_info.get("pageCount")
            if not isinstance(page_count, int):
                page_count = None

            # Preserve the provider amount and currency; do not convert currencies.
            sale_info = item.get("saleInfo", {})
            price = None
            price_source = None
            price_currency = None
            retail_price = sale_info.get("retailPrice") or sale_info.get("listPrice")
            if retail_price:
                amount = retail_price.get("amount")
                currency = retail_price.get("currencyCode")
                if amount and amount > 0:
                    price = float(amount)
                    price_currency = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
                    price_source = (
                        f"Google Books ({price_currency})"
                        if price_currency
                        else "Google Books (currency unknown)"
                    )

            candidates.append(
                normalize_candidate(
                    title=b_title,
                    author=author_str,
                    publisher=publisher,
                    price=price,
                    price_source=price_source,
                    price_currency=price_currency,
                    source="Google Books",
                    subjects=subjects,
                    edition_keys=edition_keys,
                    published_date=v_info.get("publishedDate"),
                    publication_year=int(v_info["publishedDate"][:4]) if isinstance(v_info.get("publishedDate"), str) and v_info["publishedDate"][:4].isdigit() else None,
                    edition=v_info.get("edition"),
                    language=v_info.get("language"),
                    page_count=page_count,
                    description=v_info.get("description"),
                    isbn=next((normalize_isbn(value) for value in isbn_values if normalize_isbn(value)), None),
                    subtitle=v_info.get("subtitle"),
                    cover_image_url=(v_info.get("imageLinks") or {}).get("thumbnail"),
                )
            )
        if status is not None and rate_limited:
            status["Google Books"] = "rate_limited"
        elif status is not None and candidates:
            status["Google Books"] = "success"
        elif status is not None and status.get("Google Books") == "pending":
            status["Google Books"] = "no_match"
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        if status is not None:
            status["Google Books"] = "unavailable"
        logger.warning("Google Books query unavailable: %r", exc)
    except Exception as exc:
        if status is not None:
            status["Google Books"] = "unavailable"
        logger.warning("Google Books query failed: %r", exc)

    return candidates


async def query_open_library(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query Open Library API (no key required, public)."""
    candidates: list[dict[str, Any]] = []

    # If ISBN is given, try Open Library ISBN endpoint first
    if isbn:
        clean = clean_isbn(isbn)
        url = f"https://openlibrary.org/isbn/{clean}.json"
        try:
            resp = await client.get(url, follow_redirects=True, headers=PROVIDER_HEADERS, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data, dict):
                    data = {}
                b_title = data.get("title")
                if b_title:
                    publishers = data.get("publishers", [])
                    pub_str = publishers[0] if publishers else None
                    edition_keys = {
                        f"isbn:{value.replace('-', '')}"
                        for value in data.get("isbn_10", []) + data.get("isbn_13", [])
                        if isinstance(value, str) and value.strip()
                    }
                    isbn_values = data.get("isbn_13", []) + data.get("isbn_10", [])

                    # Authors in ISBN endpoint are usually references like {'key': '/authors/OL...'}
                    author_names = []
                    for auth_ref in data.get("authors", []):
                        if isinstance(auth_ref, dict) and "key" in auth_ref:
                            try:
                                a_resp = await client.get(
                                    f"https://openlibrary.org{auth_ref['key']}.json",
                                    headers=PROVIDER_HEADERS,
                                    timeout=TIMEOUT_SECONDS,
                                )
                                if a_resp.status_code == 200:
                                    author_names.append(a_resp.json().get("name", ""))
                            except Exception:
                                pass
                    author_str = ", ".join(filter(None, author_names)) or None
                    languages = [
                        item.get("key", "").rsplit("/", 1)[-1]
                        for item in data.get("languages", [])
                        if isinstance(item, dict) and item.get("key")
                    ]
                    page_count = data.get("number_of_pages")
                    if not isinstance(page_count, int):
                        page_count = None

                    # If edition has no subjects or description, enrich from linked works record
                    subjects = [
                        subject
                        for subject in data.get("subjects", [])
                        if isinstance(subject, str) and subject.strip()
                    ]
                    desc = description_text(data.get("description"))
                    if (not subjects or not desc) and data.get("works"):
                        for work_ref in data.get("works", []):
                            if isinstance(work_ref, dict) and "key" in work_ref:
                                try:
                                    w_resp = await client.get(
                                        f"https://openlibrary.org{work_ref['key']}.json",
                                        follow_redirects=True,
                                        headers=PROVIDER_HEADERS,
                                        timeout=TIMEOUT_SECONDS,
                                    )
                                    if w_resp.status_code == 200:
                                        w_data = w_resp.json()
                                        if isinstance(w_data, dict):
                                            if not subjects:
                                                subjects = [
                                                    s
                                                    for s in w_data.get("subjects", [])
                                                    if isinstance(s, str) and s.strip()
                                                ]
                                            if not desc:
                                                desc = description_text(w_data.get("description"))
                                            break
                                except Exception:
                                    pass

                    candidates.append(
                        normalize_candidate(
                            title=b_title,
                            author=author_str,
                            publisher=pub_str,
                            source="Open Library",
                            subjects=subjects,
                            edition_keys=edition_keys,
                            published_date=data.get("publish_date"),
                            publication_year=int(data["publish_date"][-4:]) if isinstance(data.get("publish_date"), str) and data["publish_date"][-4:].isdigit() else None,
                            edition=data.get("edition_name"),
                            language=", ".join(languages) or None,
                            page_count=page_count,
                            description=desc,
                            isbn=next((normalize_isbn(value) for value in isbn_values if normalize_isbn(value)), None),
                            subtitle=data.get("subtitle"),
                            series=first_text(data.get("series")),
                            cover_image_url=(
                                f"https://covers.openlibrary.org/b/id/{data['covers'][0]}-L.jpg"
                                if isinstance(data.get("covers"), list) and data["covers"]
                                and isinstance(data["covers"][0], int)
                                else None
                            ),
                        )
                    )
                    if status is not None:
                        status["Open Library"] = "success"
                    return candidates
            elif status is not None and resp.status_code == 429:
                status["Open Library"] = "rate_limited"
        except Exception as exc:
            if status is not None:
                status["Open Library"] = "unavailable"
            logger.warning("Open Library ISBN query failed: %r", exc)

    # General Open Library search query. Search several title forms because the
    # API's work-level result often omits edition publishers.
    params: dict[str, Any] = {"limit": 5}
    if isbn:
        params["isbn"] = clean_isbn(isbn)
    if title:
        params["title"] = title.strip()
    if author:
        params["author"] = author.strip()
    if query and not (title or author or isbn):
        params["q"] = query.strip()

    if len(params) == 1 and "limit" in params:
        if status is not None and status.get("Open Library") == "pending":
            status["Open Library"] = "no_match"
        return candidates

    url = "https://openlibrary.org/search.json"
    try:
        search_params = [params]
        if title and not isbn:
            base_title = _title_variants(title)[0] if _title_variants(title) else title.strip()
            search_params = [{**params, "title": base_title}]
            if any("\u0d00" <= char <= "\u0d7f" for char in title):
                latin_title = transliterate_malayalam_to_latin(title)
                if latin_title and latin_title != base_title:
                    search_params.append({**params, "title": latin_title})
            else:
                variants = _title_variants(title)
                if len(variants) > 1 and variants[1] != base_title:
                    search_params.append({**params, "title": variants[1]})
            if publisher:
                for variant_params in search_params:
                    variant_params["publisher"] = publisher.strip()

        docs: list[dict[str, Any]] = []
        seen_docs: set[str] = set()
        last_status: int | None = None
        for search_params_item in search_params:
            resp = await client.get(
                url,
                params=search_params_item,
                headers=PROVIDER_HEADERS,
                timeout=TIMEOUT_SECONDS,
            )
            last_status = resp.status_code
            if resp.status_code != 200:
                if status is not None:
                    status["Open Library"] = "rate_limited" if resp.status_code == 429 else "unavailable"
                logger.warning("Open Library search returned HTTP %s for title query", resp.status_code)
                continue
            data = resp.json()
            for doc in (data.get("docs", []) if isinstance(data, dict) else []):
                key = str(doc.get("key") or doc.get("title") or "")
                if key not in seen_docs:
                    seen_docs.add(key)
                    docs.append(doc)
        edition_enrichment_calls = 0
        if docs:
            for doc in docs:
                b_title = doc.get("title")
                if not b_title:
                    continue
                author_names = doc.get("author_name", [])
                author_str = ", ".join(author_names) if author_names else None
                publishers = doc.get("publisher", [])
                pub_str = publishers[0] if publishers else None
                if not pub_str and doc.get("key") and edition_enrichment_calls < 2:
                    try:
                        edition_enrichment_calls += 1
                        editions_resp = await client.get(
                            f"https://openlibrary.org{doc['key']}/editions.json",
                            params={"limit": 10},
                            headers=PROVIDER_HEADERS,
                            timeout=TIMEOUT_SECONDS,
                        )
                        if editions_resp.status_code == 200:
                            edition_docs = editions_resp.json().get("entries", [])
                            for edition_doc in edition_docs:
                                edition_publishers = edition_doc.get("publishers", [])
                                candidate_publisher = first_text(edition_publishers)
                                candidate_title = edition_doc.get("title")
                                if candidate_publisher and (
                                    not candidate_title or _titles_compatible(b_title, candidate_title)
                                ):
                                    pub_str = candidate_publisher
                                    break
                    except Exception as exc:
                        logger.warning("Open Library edition enrichment failed (%s): %r", type(exc).__name__, exc)
                page_count = doc.get("number_of_pages_median")
                if not isinstance(page_count, int):
                    page_count = None
                languages = doc.get("language", [])
                language = ", ".join(languages) if isinstance(languages, list) else first_text(languages)
                published_date = first_text(doc.get("publish_date"))
                edition = first_text(doc.get("edition_name"))
                edition_keys = {
                    f"isbn:{value.replace('-', '')}"
                    for value in doc.get("isbn", [])
                    if isinstance(value, str) and value.strip()
                }
                isbn_values = doc.get("isbn", [])

                candidates.append(
                    normalize_candidate(
                        title=b_title,
                        author=author_str,
                        publisher=pub_str,
                        source="Open Library",
                        subjects=[
                            subject
                            for subject in doc.get("subject", [])
                            if isinstance(subject, str) and subject.strip()
                        ],
                        edition_keys=edition_keys,
                        published_date=published_date,
                        publication_year=int(published_date[-4:]) if published_date and published_date[-4:].isdigit() else None,
                        edition=edition,
                        language=language,
                        page_count=page_count,
                        description=(
                            description_text(doc.get("description"))
                            or description_text(doc.get("first_sentence"))
                        ),
                        isbn=next((normalize_isbn(value) for value in isbn_values if normalize_isbn(value)), None),
                        subtitle=doc.get("subtitle"),
                        series=first_text(doc.get("series")),
                    )
                )
            if status is not None:
                status["Open Library"] = "success" if candidates else "no_match"
        elif status is not None:
            if last_status == 200:
                status["Open Library"] = "no_match"
            else:
                status["Open Library"] = "rate_limited" if last_status == 429 else "unavailable"
                logger.warning("Open Library search returned HTTP %s with no usable documents", last_status)
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        if status is not None:
            status["Open Library"] = "unavailable"
        logger.warning("Open Library search unavailable (%s): %r", type(exc).__name__, exc)
    except Exception as exc:
        if status is not None:
            status["Open Library"] = "unavailable"
        logger.warning("Open Library search failed (%s): %r", type(exc).__name__, exc)

    return candidates


async def query_library_of_congress(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query the Library of Congress catalogue through its documented SRU gateway."""
    search_term = clean_isbn(isbn) if isbn else (title or query or author or "").strip()
    if not search_term:
        if status is not None:
            status["Library of Congress"] = "no_match"
        return []

    if isbn:
        cql_query = f"bath.isbn={clean_isbn(isbn)}"
    elif title and author:
        cql_query = f'dc.title="{title.strip()}" AND dc.creator="{author.strip()}"'
    elif title:
        cql_query = f'dc.title="{title.strip()}"'
    elif author:
        cql_query = f'dc.creator="{author.strip()}"'
    else:
        cql_query = f'dc.title="{search_term}"'

    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": cql_query,
        "startRecord": 1,
        "maximumRecords": 5,
        "recordSchema": "mods",
    }
    candidates: list[dict[str, Any]] = []
    try:
        response = await client.get(
            LOC_SRU_URL,
            params=params,
            headers=PROVIDER_HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            if status is not None:
                status["Library of Congress"] = "rate_limited" if response.status_code == 429 else "unavailable"
            return candidates

        root = ET.fromstring(response.text)
        for record_data in _xml_children(root, "recordData"):
            mods = next(
                (child for child in list(record_data) if child.tag.rsplit("}", 1)[-1] == "mods"),
                record_data,
            )
            record_title = _first_xml_text(mods, "title")
            if not record_title:
                continue
            title_info = next(
                (child for child in _xml_children(mods, "titleInfo") if _first_xml_text(child, "title")),
                None,
            )
            subtitle = _first_xml_text(title_info, "subTitle") if title_info is not None else None
            names = [
                _xml_text(name_part)
                for name in _xml_children(mods, "name")
                for name_part in _xml_children(name, "namePart")
                if _xml_text(name_part)
            ]
            identifiers = [
                _xml_text(identifier)
                for identifier in _xml_children(mods, "identifier")
                if (_xml_text(identifier) and (identifier.get("type") or "").lower() == "isbn")
            ]
            publisher = _first_xml_text(mods, "publisher")
            published_date = _first_xml_text(mods, "dateIssued")
            extent = _first_xml_text(mods, "extent")
            page_match = re.search(r"\b(\d+)\s+p", extent or "", re.IGNORECASE)
            candidates.append(
                normalize_candidate(
                    title=record_title,
                    author=", ".join(dict.fromkeys(names)) or None,
                    publisher=publisher,
                    source="Library of Congress",
                    subjects=[
                        value
                        for subject in _xml_children(mods, "subject")
                        for value in [_first_xml_text(subject, "topic")]
                        if value
                    ],
                    published_date=published_date,
                    publication_year=_parse_year(published_date),
                    edition=_first_xml_text(mods, "edition"),
                    language=_first_xml_text(mods, "languageTerm"),
                    page_count=int(page_match.group(1)) if page_match else None,
                    description=_first_xml_text(mods, "abstract"),
                    isbn=_first_isbn(identifiers),
                    subtitle=subtitle,
                    editor=", ".join(
                        dict.fromkeys(
                            value
                            for name in _xml_children(mods, "name")
                            if (name.get("type") or "").lower() == "editor"
                            for value in [_xml_text(part) for part in _xml_children(name, "namePart")]
                            if value
                        )
                    ) or None,
                )
            )
        if status is not None:
            status["Library of Congress"] = "success" if candidates else "no_match"
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        if status is not None:
            status["Library of Congress"] = "unavailable"
        logger.warning("Library of Congress SRU unavailable: %r", exc)
    except (ET.ParseError, AttributeError, ValueError, TypeError) as exc:
        if status is not None:
            status["Library of Congress"] = "unavailable"
        logger.warning("Library of Congress SRU response invalid: %r", exc)
    return candidates


async def query_internet_archive(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query Internet Archive's public Advanced Search metadata endpoint."""
    search_term = clean_isbn(isbn) if isbn else (title or query or author or "").strip()
    if not search_term:
        if status is not None:
            status["Internet Archive"] = "no_match"
        return []

    if isbn:
        archive_query = f'isbn:"{clean_isbn(isbn)}"'
    elif title and author:
        archive_query = f'title:"{title.strip()}" AND creator:"{author.strip()}"'
    elif title:
        archive_query = f'title:"{title.strip()}"'
    elif author:
        archive_query = f'creator:"{author.strip()}"'
    else:
        archive_query = search_term

    params = {
        "q": f"mediatype:texts AND ({archive_query})",
        "fl[]": ["identifier", "title", "creator", "publisher", "date", "language", "description", "subject", "isbn", "edition", "subtitle", "series", "volume", "pages"],
        "rows": 5,
        "page": 1,
        "output": "json",
    }
    candidates: list[dict[str, Any]] = []
    try:
        response = await client.get(
            INTERNET_ARCHIVE_SEARCH_URL,
            params=params,
            headers=PROVIDER_HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            if status is not None:
                status["Internet Archive"] = "rate_limited" if response.status_code == 429 else "unavailable"
            return candidates
        data = response.json()
        docs = data.get("response", {}).get("docs", []) if isinstance(data, dict) else []
        for doc in docs:
            if not isinstance(doc, dict) or not doc.get("title"):
                continue
            if _is_junk_title(first_text(doc.get("title")), title or query):
                continue
            isbn_value = _first_isbn(doc.get("isbn"))
            candidates.append(
                normalize_candidate(
                    title=first_text(doc.get("title")) or "",
                    author=first_text(doc.get("creator")),
                    publisher=first_text(doc.get("publisher")),
                    source="Internet Archive",
                    subjects=doc.get("subject") if isinstance(doc.get("subject"), list) else [],
                    published_date=first_text(doc.get("date")),
                    publication_year=_parse_year(first_text(doc.get("date"))),
                    edition=first_text(doc.get("edition")),
                    language=first_text(doc.get("language")),
                    description=description_text(doc.get("description")),
                    isbn=isbn_value,
                    subtitle=first_text(doc.get("subtitle")),
                    series=first_text(doc.get("series")),
                    volume=first_text(doc.get("volume")),
                    page_count=(
                        int(doc["pages"])
                        if isinstance(doc.get("pages"), (int, str)) and str(doc["pages"]).isdigit()
                        else None
                    ),
                )
            )
        if status is not None:
            status["Internet Archive"] = "success" if candidates else "no_match"
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        if status is not None:
            status["Internet Archive"] = "unavailable"
        logger.warning("Internet Archive search unavailable: %r", exc)
    except (ValueError, TypeError, KeyError) as exc:
        if status is not None:
            status["Internet Archive"] = "unavailable"
        logger.warning("Internet Archive response invalid: %r", exc)
    return candidates


WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
# Kept as a compatibility alias for callers/tests that used the old constant.
WIKIDATA_SPARQL_URL = WIKIDATA_API_URL


async def query_wikidata(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Query Wikidata's bounded MediaWiki API for book metadata."""
    search_term = clean_isbn(isbn) if isbn else (title or query or "").strip()
    if not search_term:
        if status is not None:
            status["Wikidata"] = "no_match"
        return []

    is_malayalam = any("\u0d00" <= char <= "\u0d7f" for char in search_term)
    language = "ml" if is_malayalam else "en"
    common_params = {
        "action": "wbsearchentities",
        "search": search_term,
        "format": "json",
        "type": "item",
        "limit": 5,
        "language": language,
        "uselang": language,
    }
    try:
        response = await client.get(
            WIKIDATA_API_URL,
            params=common_params,
            headers=PROVIDER_HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            if status is not None:
                status["Wikidata"] = "rate_limited" if response.status_code == 429 else "unavailable"
            logger.warning("Wikidata MediaWiki search returned HTTP %s", response.status_code)
            return []
        search_data = response.json()
        search_results = search_data.get("search", []) if isinstance(search_data, dict) else []
        qids = [
            item.get("id")
            for item in search_results[:3]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].startswith("Q")
        ]
        if not qids:
            if status is not None:
                status["Wikidata"] = "no_match"
            return []

        entity_response = await client.get(
            WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "props": "labels|descriptions|claims",
                "languages": "ml|en",
                "format": "json",
            },
            headers=PROVIDER_HEADERS,
            timeout=TIMEOUT_SECONDS,
        )
        if entity_response.status_code != 200:
            if status is not None:
                status["Wikidata"] = "rate_limited" if entity_response.status_code == 429 else "unavailable"
            logger.warning("Wikidata entity lookup returned HTTP %s", entity_response.status_code)
            return []
        entity_data = entity_response.json()
        entities = entity_data.get("entities", {}) if isinstance(entity_data, dict) else {}

        def claim_values(claims: dict[str, Any], property_id: str) -> list[Any]:
            values = []
            for claim in claims.get(property_id, []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if value is not None:
                    values.append(value)
            return values

        book_instance_ids = {"Q571", "Q8261", "Q7725634", "Q47461344"}
        selected: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        related_qids: set[str] = set()
        for qid in qids:
            entity = entities.get(qid, {})
            claims = entity.get("claims", {}) if isinstance(entity, dict) else {}
            instance_ids = {
                value.get("id") for value in claim_values(claims, "P31")
                if isinstance(value, dict) and isinstance(value.get("id"), str)
            }
            has_book_fields = any(claims.get(prop) for prop in ("P50", "P123", "P212", "P957"))
            if not (instance_ids & book_instance_ids or has_book_fields):
                continue
            selected.append((qid, entity, claims))
            for prop in ("P50", "P123"):
                related_qids.update(
                    value["id"] for value in claim_values(claims, prop)
                    if isinstance(value, dict) and isinstance(value.get("id"), str)
                )

        related_labels: dict[str, str] = {}
        if related_qids:
            label_response = await client.get(
                WIKIDATA_API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(sorted(related_qids)),
                    "props": "labels",
                    "languages": "ml|en",
                    "format": "json",
                },
                headers=PROVIDER_HEADERS,
                timeout=TIMEOUT_SECONDS,
            )
            if label_response.status_code == 200:
                label_data = label_response.json()
                for qid, entity in (label_data.get("entities", {}) if isinstance(label_data, dict) else {}).items():
                    labels = entity.get("labels", {}) if isinstance(entity, dict) else {}
                    label = labels.get(language) or labels.get("en") or labels.get("ml")
                    if isinstance(label, dict) and label.get("value"):
                        related_labels[qid] = label["value"]
            else:
                logger.warning("Wikidata related-label lookup returned HTTP %s", label_response.status_code)

        candidates: list[dict[str, Any]] = []
        for _, entity, claims in selected:
            labels = entity.get("labels", {}) if isinstance(entity, dict) else {}
            title_item = labels.get(language) or labels.get("en") or labels.get("ml")
            work_title = title_item.get("value") if isinstance(title_item, dict) else None
            if not work_title:
                continue
            author_names = [
                related_labels[value["id"]]
                for value in claim_values(claims, "P50")
                if isinstance(value, dict) and value.get("id") in related_labels
            ]
            publisher_names = [
                related_labels[value["id"]]
                for value in claim_values(claims, "P123")
                if isinstance(value, dict) and value.get("id") in related_labels
            ]
            isbn_value = _first_isbn([
                value for prop in ("P212", "P957") for value in claim_values(claims, prop)
            ])
            publication_date = first_text([
                value.get("time") for value in claim_values(claims, "P577")
                if isinstance(value, dict) and value.get("time")
            ])
            page_values = claim_values(claims, "P1104")
            page_count = next((value for value in page_values if isinstance(value, int)), None)
            candidates.append(
                normalize_candidate(
                    title=work_title,
                    author=", ".join(author_names) or None,
                    publisher=", ".join(publisher_names) or None,
                    source="Wikidata",
                    published_date=publication_date,
                    publication_year=_parse_year(publication_date),
                    page_count=page_count,
                    isbn=isbn_value,
                )
            )
        if status is not None:
            status["Wikidata"] = "success" if candidates else "no_match"
        return candidates
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        if status is not None:
            status["Wikidata"] = "unavailable"
        logger.warning("Wikidata SPARQL unavailable: %r", exc)
    except (ValueError, TypeError, KeyError) as exc:
        if status is not None:
            status["Wikidata"] = "unavailable"
        logger.warning("Wikidata SPARQL response invalid: %r", exc)
    return []


async def search_metadata(
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    query: str | None = None,
) -> MetadataSearchResults:
    """
    Search multiple metadata providers with fallback.
    Returns deduplicated list of candidates.
    """
    all_candidates: list[dict[str, Any]] = []
    provider_status = {
        "Google Books": "pending",
        "Open Library": "pending",
        "Library of Congress": "pending",
        "Internet Archive": "pending",
        "Wikidata": "pending",
        "Google Web Discovery": "pending",
    }

    async with httpx.AsyncClient(headers=PROVIDER_HEADERS) as client:
        from .web_search_provider import query_web_discovery
        tasks = [
            query_google_books(client=client, query=query, isbn=isbn, title=title, author=author, publisher=publisher, status=provider_status),
            query_open_library(client=client, query=query, isbn=isbn, title=title, author=author, publisher=publisher, status=provider_status),
            query_library_of_congress(client=client, query=query, isbn=isbn, title=title, author=author, status=provider_status),
            query_internet_archive(client=client, query=query, isbn=isbn, title=title, author=author, status=provider_status),
            query_wikidata(client=client, query=query, isbn=isbn, title=title, author=author, status=provider_status),
            query_web_discovery(client=client, query=query, isbn=isbn, title=title, author=author, status=provider_status),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_candidates.extend(res)
            elif isinstance(res, Exception):
                logger.warning("Provider query failed with exception: %r", res)

    # Drop explicit title/author mismatches before aggregation. Missing author is
    # allowed because many catalogue records do not provide it.
    requested_title = title or query
    if requested_title:
        all_candidates = [
            candidate for candidate in all_candidates
            if not _is_junk_title(candidate.get("title"), requested_title)
            if _title_match_rank(requested_title, candidate.get("title")) < 3
            and (not author or not candidate.get("author") or _author_match_rank(author, candidate.get("author")) < 3)
        ]

    # Merge matching editions or same title/author records with missing fields.
    # Distinct publishers for different editions remain separate candidates.
    unique_candidates: list[dict[str, Any]] = []
    conflicts: list[str] = []
    merge_fields = (
        "author", "publisher", "price", "price_currency", "price_source",
        "published_date", "publication_year", "edition", "language",
        "page_count", "description", "subtitle", "editor", "translator",
        "series", "volume", "cover_image_url", "source_url",
    )
    for cand in all_candidates:
        match = None
        for existing in unique_candidates:
            same_isbn = bool(existing["isbn"] and cand["isbn"] and existing["isbn"] == cand["isbn"])
            # Compatibility is enough for search filtering, but aggregation
            # must not collapse subtitles, omnibuses, or adaptations into the
            # standalone title candidate.
            same_title = _match_key(existing["title"]) == _match_key(cand["title"])
            same_title_author = same_title and _authors_compatible(existing.get("author"), cand.get("author"))
            both_without_isbn = not existing["isbn"] and not cand["isbn"]
            existing_publisher = _match_key(existing.get("publisher"))
            incoming_publisher = _match_key(cand.get("publisher"))
            same_or_missing_publisher = (
                not existing_publisher
                or not incoming_publisher
                or existing_publisher == incoming_publisher
                or existing_publisher in incoming_publisher
                or incoming_publisher in existing_publisher
            )
            compatible_publisher = (
                existing["publisher"] is None
                or not incoming_publisher
                or existing_publisher == incoming_publisher
                or existing_publisher in incoming_publisher
                or incoming_publisher in existing_publisher
            )
            # 1. Exact matching ISBN represents the same physical book edition
            # A provider can return a malformed record carrying the requested
            # ISBN. Do not merge incompatible titles under one ISBN; keep both
            # candidates so the librarian can see the conflict.
            if same_isbn and same_title and same_or_missing_publisher:
                match = existing
                break
            # 2. For books without ISBN, match by title + author + compatible publisher
            if both_without_isbn and same_title_author and compatible_publisher:
                match = existing
                break

        if match is None:
            unique_candidates.append(cand)
            continue

        # Backfill missing fields from matching candidate
        for field in merge_fields:
            if match.get(field) is None and cand.get(field) is not None:
                match[field] = cand[field]
            # If publisher is more descriptive (e.g. "Penguin Classics" vs "Penguin"), prefer the more descriptive name
            elif field == "publisher" and match.get("publisher") and cand.get("publisher"):
                existing_pub = match["publisher"].strip()
                incoming_pub = cand["publisher"].strip()
                if len(incoming_pub) > len(existing_pub) and existing_pub.lower() in incoming_pub.lower():
                    match["publisher"] = incoming_pub

        # Provenance tracking
        provenance = match.setdefault("field_provenance", {})
        for field, sources in cand.get("field_provenance", {}).items():
            field_sources = provenance.setdefault(field, [])
            for source in sources:
                if source not in field_sources:
                    field_sources.append(source)

        # Conflict tracking across distinct providers
        conflicts_by_field = match.setdefault("field_conflicts", {})
        for field in (
            "publisher", "price", "author", "published_date", "publication_year",
            "language", "edition",
        ):
            existing_value = match.get(field)
            incoming_value = cand.get(field)
            if (
                existing_value is not None
                and incoming_value is not None
                and str(existing_value).casefold() != str(incoming_value).casefold()
            ):
                # Don't flag as conflict if one publisher is a substring of another (e.g. Penguin vs Penguin Classics)
                if field == "publisher" and (
                    str(existing_value).casefold() in str(incoming_value).casefold()
                    or str(incoming_value).casefold() in str(existing_value).casefold()
                ):
                    continue
                values = conflicts_by_field.setdefault(field, [])
                for value in (existing_value, incoming_value):
                    if value not in values:
                        values.append(value)

        match["subjects"] = list(dict.fromkeys(match["subjects"] + cand["subjects"]))
        match["_edition_keys"].update(cand["_edition_keys"])
        sources = [value.strip() for value in match["source"].split(",")]
        if cand["source"] not in sources:
            match["source"] = f"{match['source']}, {cand['source']}"

    requested_isbn = normalize_isbn(isbn)
    if requested_isbn:
        # ISBN lookup must never return a different or unidentified edition.
        unique_candidates = [
            candidate for candidate in unique_candidates
            if candidate.get("isbn") == requested_isbn
        ]
        for candidate in unique_candidates:
            candidate["match_status"] = "exact_isbn"
        seen_titles: dict[str, str] = {}
        for candidate in unique_candidates:
            title_key = candidate["title"].strip().casefold()
            prior_title = seen_titles.get(candidate["isbn"])
            if prior_title is not None and prior_title != title_key:
                conflicts.append(candidate["isbn"])
            seen_titles[candidate["isbn"]] = title_key
    else:
        for candidate in unique_candidates:
            sources = [value.strip() for value in candidate["source"].split(",")]
            candidate["match_status"] = (
                "verified_alternative"
                if len(sources) > 1 and candidate.get("isbn")
                else "unverified_search"
            )

    if requested_title:
        unique_candidates.sort(
            key=lambda candidate: (
                _title_match_rank(requested_title, candidate.get("title")),
                _author_match_rank(author, candidate.get("author")),
                _candidate_language_rank(candidate, requested_title),
                _candidate_quality_penalty(candidate, requested_title),
                0 if candidate.get("publisher") else 1,
                0 if candidate.get("subjects") else 1,
            )
        )

    for candidate in unique_candidates:
        candidate.pop("_edition_keys", None)

    if unique_candidates:
        result_status = ("conflicting_exact_matches" if conflicts else "exact_match") if requested_isbn else (
            "conflicting_exact_matches" if conflicts else unique_candidates[0]["match_status"]
        )
    elif all(
        value in {"unavailable", "rate_limited", "not_configured", "pending", "no_match"}
        for value in provider_status.values()
    ) and any(value in {"unavailable", "rate_limited"} for value in provider_status.values()):
        result_status = "provider_unavailable"
    else:
        result_status = "no_match_found"

    return MetadataSearchResults(
        unique_candidates,
        result_status=result_status,
        provider_status=provider_status,
        conflicts=conflicts,
    )
