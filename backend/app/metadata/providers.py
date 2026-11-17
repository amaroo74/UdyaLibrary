"""
Online book metadata providers with fallback support (Open Library & Google Books).
Strictly normalizes results to approved fields only: title, author, publisher, suggested price.
Never persists or exposes ISBN or edition as saved catalogue fields.
"""

import logging
import re
from typing import Any
import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6.0


def clean_isbn(isbn: str) -> str:
    """Strip hyphens and whitespace from ISBN."""
    return re.sub(r"[^0-9X]", "", isbn.upper())


def normalize_candidate(
    title: str,
    author: str | None = None,
    publisher: str | None = None,
    price: float | None = None,
    price_source: str | None = None,
    source: str = "unknown",
    subjects: list[str] | None = None,
    edition_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize book metadata into approved persistent fields only."""
    return {
        "title": title.strip() if title else "",
        "author": author.strip() if author else None,
        "publisher": publisher.strip() if publisher else None,
        "price": float(price) if price is not None and price > 0 else None,
        "price_source": price_source if price is not None and price > 0 else None,
        "source": source,
        "subjects": list(dict.fromkeys(subjects or [])),
        "_edition_keys": edition_keys or set(),
    }


async def query_google_books(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """Query Google Books Volumes API without scraping or requiring an API key."""
    candidates: list[dict[str, Any]] = []
    q_parts = []
    if isbn:
        clean = clean_isbn(isbn)
        q_parts.append(f"isbn:{clean}")
    if title:
        q_parts.append(f'intitle:"{title.strip()}"')
    if author:
        q_parts.append(f'inauthor:"{author.strip()}"')
    if query and not q_parts:
        q_parts.append(query.strip())

    if not q_parts:
        return candidates

    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": " ".join(q_parts), "maxResults": 5, "printType": "books"}

    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning("Google Books returned status %s", resp.status_code)
            return candidates

        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else []
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
            subjects = [
                subject
                for subject in v_info.get("categories", [])
                if isinstance(subject, str) and subject.strip()
            ]

            # Check for suggested retail price in INR or converted
            sale_info = item.get("saleInfo", {})
            price = None
            price_source = None
            retail_price = sale_info.get("retailPrice") or sale_info.get("listPrice")
            if retail_price:
                amount = retail_price.get("amount")
                currency = retail_price.get("currencyCode", "INR")
                if amount and amount > 0:
                    price = float(amount)
                    price_source = f"Google Books ({currency})"

            candidates.append(
                normalize_candidate(
                    title=b_title,
                    author=author_str,
                    publisher=publisher,
                    price=price,
                    price_source=price_source,
                    source="Google Books",
                    subjects=subjects,
                    edition_keys=edition_keys,
                )
            )
    except Exception as exc:
        logger.warning("Google Books query failed: %s", exc)

    return candidates


async def query_open_library(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
) -> list[dict[str, Any]]:
    """Query Open Library API (no key required, public)."""
    candidates: list[dict[str, Any]] = []

    # If ISBN is given, try Open Library ISBN endpoint first
    if isbn:
        clean = clean_isbn(isbn)
        url = f"https://openlibrary.org/isbn/{clean}.json"
        try:
            resp = await client.get(url, follow_redirects=True, timeout=TIMEOUT_SECONDS)
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

                    # Authors in ISBN endpoint are usually references like {'key': '/authors/OL...'}
                    author_names = []
                    for auth_ref in data.get("authors", []):
                        if isinstance(auth_ref, dict) and "key" in auth_ref:
                            try:
                                a_resp = await client.get(
                                    f"https://openlibrary.org{auth_ref['key']}.json",
                                    timeout=TIMEOUT_SECONDS,
                                )
                                if a_resp.status_code == 200:
                                    author_names.append(a_resp.json().get("name", ""))
                            except Exception:
                                pass
                    author_str = ", ".join(filter(None, author_names)) or None

                    candidates.append(
                        normalize_candidate(
                            title=b_title,
                            author=author_str,
                            publisher=pub_str,
                            source="Open Library",
                            subjects=[
                                subject
                                for subject in data.get("subjects", [])
                                if isinstance(subject, str) and subject.strip()
                            ],
                            edition_keys=edition_keys,
                        )
                    )
                    return candidates
        except Exception as exc:
            logger.warning("Open Library ISBN query failed: %s", exc)

    # General Open Library search query
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
        return candidates

    url = "https://openlibrary.org/search.json"
    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            docs = data.get("docs", []) if isinstance(data, dict) else []
            for doc in docs:
                b_title = doc.get("title")
                if not b_title:
                    continue
                author_names = doc.get("author_name", [])
                author_str = ", ".join(author_names) if author_names else None
                publishers = doc.get("publisher", [])
                pub_str = publishers[0] if publishers else None
                edition_keys = {
                    f"isbn:{value.replace('-', '')}"
                    for value in doc.get("isbn", [])
                    if isinstance(value, str) and value.strip()
                }

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
                    )
                )
    except Exception as exc:
        logger.warning("Open Library search failed: %s", exc)

    return candidates


async def search_metadata(
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """
    Search multiple metadata providers with fallback.
    Returns deduplicated list of candidates.
    """
    all_candidates: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers={"User-Agent": "UdayaLibrary/0.1.0"}) as client:
        # 1. Query Google Books
        gb_candidates = await query_google_books(
            client=client, query=query, isbn=isbn, title=title, author=author
        )
        all_candidates.extend(gb_candidates)

        # 2. Query Open Library as fallback or complementary
        ol_candidates = await query_open_library(
            client=client, query=query, isbn=isbn, title=title, author=author
        )
        all_candidates.extend(ol_candidates)

    # Merge only matching editions or same title/author records with one missing
    # publisher. Distinct publishers remain separate edition candidates.
    unique_candidates: list[dict[str, Any]] = []
    for cand in all_candidates:
        title_key = cand["title"].strip().lower()
        author_key = (cand["author"] or "").strip().lower()
        publisher_key = (cand["publisher"] or "").strip().lower()
        match = None
        for existing in unique_candidates:
            same_title_author = (
                existing["title"].strip().lower() == title_key
                and (existing["author"] or "").strip().lower() == author_key
            )
            same_edition = bool(existing["_edition_keys"] & cand["_edition_keys"])
            compatible_publisher = (
                existing["publisher"] is None
                or not publisher_key
                or existing["publisher"].strip().lower() == publisher_key
            )
            if same_edition or (same_title_author and compatible_publisher):
                match = existing
                break

        if match is None:
            unique_candidates.append(cand)
            continue

        if not match["publisher"] and cand["publisher"]:
            match["publisher"] = cand["publisher"]
        if match["price"] is None and cand["price"] is not None:
            match["price"] = cand["price"]
            match["price_source"] = cand["price_source"]
        match["subjects"] = list(dict.fromkeys(match["subjects"] + cand["subjects"]))
        match["_edition_keys"].update(cand["_edition_keys"])
        sources = [value.strip() for value in match["source"].split(",")]
        if cand["source"] not in sources:
            match["source"] = f"{match['source']}, {cand['source']}"

    for candidate in unique_candidates:
        candidate.pop("_edition_keys", None)
    return unique_candidates
