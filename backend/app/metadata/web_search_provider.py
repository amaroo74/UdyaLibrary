"""Web Search & Digital Discovery Provider for Malayalam and Indian Book Metadata.

Supports:
- Google Custom Search JSON API (when GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX are provided).
- Malayalam Wikisource API (open public access, no API key required).
- In-memory result caching and rate-limit preservation.
- Integration with web_extractor for structured Schema.org JSON-LD extraction.
"""

import logging
import os
import re
import time
from typing import Any
import httpx

from ..isbn import clean_isbn, normalize_isbn
from .malayalam_normalizer import (
    build_discovery_queries,
    fuzzy_match_malayalam,
    normalize_malayalam_text,
)
from .providers import normalize_candidate
from .web_extractor import extract_webpage_metadata

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_SIZE = 500

# Thread-safe in-memory cache: (query_key) -> (timestamp, candidates)
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _get_cache_key(
    isbn: str | None, title: str | None, author: str | None, query: str | None
) -> str:
    parts = [
        f"isbn:{clean_isbn(isbn)}" if isbn else "",
        f"title:{normalize_malayalam_text(title).lower()}" if title else "",
        f"author:{normalize_malayalam_text(author).lower()}" if author else "",
        f"query:{normalize_malayalam_text(query).lower()}" if query else "",
    ]
    return "|".join(p for p in parts if p)


def _get_from_cache(cache_key: str) -> list[dict[str, Any]] | None:
    if not cache_key or cache_key not in _SEARCH_CACHE:
        return None
    cached_time, candidates = _SEARCH_CACHE[cache_key]
    if time.time() - cached_time < CACHE_TTL_SECONDS:
        return [dict(c) for c in candidates]
    # Expired
    del _SEARCH_CACHE[cache_key]
    return None


def _save_to_cache(cache_key: str, candidates: list[dict[str, Any]]) -> None:
    if not cache_key:
        return
    if len(_SEARCH_CACHE) >= MAX_CACHE_SIZE:
        # Evict oldest 50 entries
        sorted_keys = sorted(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
        for old_key in sorted_keys[:50]:
            del _SEARCH_CACHE[old_key]
    _SEARCH_CACHE[cache_key] = (time.time(), [dict(c) for c in candidates])


def clear_discovery_cache() -> None:
    """Clear in-memory search cache (used in tests)."""
    _SEARCH_CACHE.clear()


async def query_malayalam_wikisource(
    client: httpx.AsyncClient,
    search_term: str,
) -> list[dict[str, Any]]:
    """Query Malayalam Wikisource public MediaWiki API for out-of-print and classic literature."""
    candidates: list[dict[str, Any]] = []
    if not search_term or len(search_term.strip()) < 2:
        return candidates

    url = "https://ml.wikisource.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": search_term.strip(),
        "srnamespace": "0",  # Main namespace
        "srlimit": "3",
        "format": "json",
    }

    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            search_items = (
                data.get("query", {}).get("search", [])
                if isinstance(data, dict)
                else []
            )
            for item in search_items:
                raw_title = item.get("title", "")
                snippet = item.get("snippet", "")
                clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()

                if raw_title:
                    cand = normalize_candidate(
                        title=normalize_malayalam_text(raw_title),
                        author=None,
                        publisher="Malayalam Wikisource",
                        source="Malayalam Wikisource",
                        description=clean_snippet or None,
                    )
                    cand["source_url"] = f"https://ml.wikisource.org/wiki/{raw_title.replace(' ', '_')}"
                    cand["field_provenance"] = {"title": ["Malayalam Wikisource"]}
                    candidates.append(cand)
    except Exception as exc:
        logger.debug("Malayalam Wikisource query failed: %s", exc)

    return candidates


async def query_google_custom_search(
    client: httpx.AsyncClient,
    search_query: str,
    api_key: str,
    cx: str,
) -> tuple[list[dict[str, Any]], str]:
    """
    Execute a query against the Google Custom Search JSON API.
    Returns (candidates, status_string).
    """
    candidates: list[dict[str, Any]] = []
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cx,
        "q": search_query,
        "num": 3,
    }

    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 429:
            return ([], "rate_limited")
        if resp.status_code != 200:
            logger.warning("Google Custom Search API returned status %s", resp.status_code)
            return ([], "unavailable")

        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else []

        for item in items:
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            title = item.get("title", "")
            pagemap = item.get("pagemap", {})

            # 1. Fast extraction from Google pagemap (Schema.org / OpenGraph already parsed by Google)
            extracted_from_pagemap = False
            metatags = pagemap.get("metatags", [])
            first_meta = metatags[0] if isinstance(metatags, list) and metatags else {}

            meta_title = first_meta.get("og:title") or first_meta.get("dc.title")
            meta_author = first_meta.get("author") or first_meta.get("dc.creator") or first_meta.get("book:author")
            meta_publisher = first_meta.get("og:site_name") or first_meta.get("dc.publisher")
            meta_isbn = first_meta.get("book:isbn") or first_meta.get("citation_isbn")
            meta_image = first_meta.get("og:image")

            if meta_title:
                cand = normalize_candidate(
                    title=normalize_malayalam_text(meta_title),
                    author=normalize_malayalam_text(meta_author) if meta_author else None,
                    publisher=normalize_malayalam_text(meta_publisher) if meta_publisher else None,
                    source=f"Google Web Discovery ({item.get('displayLink', 'Web')})",
                    isbn=normalize_isbn(clean_isbn(meta_isbn)) if meta_isbn else None,
                    description=snippet or None,
                    cover_image_url=meta_image,
                )
                cand["source_url"] = link
                cand["field_provenance"] = {"title": ["Google Custom Search"]}
                candidates.append(cand)
                extracted_from_pagemap = True

            # 2. If pagemap was empty but URL is available, attempt destination fetch if permitted
            if not extracted_from_pagemap and link.startswith("http"):
                try:
                    page_resp = await client.get(link, timeout=TIMEOUT_SECONDS)
                    if page_resp.status_code == 200:
                        page_cands = extract_webpage_metadata(page_resp.text, link)
                        candidates.extend(page_cands)
                except Exception:
                    pass

        return (candidates, "success" if candidates else "no_match")

    except httpx.TimeoutException:
        return ([], "unavailable")
    except Exception as exc:
        logger.warning("Google Custom Search request failed: %s", exc)
        return ([], "unavailable")


async def query_web_discovery(
    client: httpx.AsyncClient,
    query: str | None = None,
    isbn: str | None = None,
    title: str | None = None,
    author: str | None = None,
    status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Query web discovery layer (Google Custom Search + Open Malayalam Repositories).
    """
    cache_key = _get_cache_key(isbn, title, author, query)
    cached = _get_from_cache(cache_key)
    if cached is not None:
        if status is not None:
            status["Google Web Discovery"] = "success" if cached else "no_match"
        return cached

    api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_CX", "").strip()

    discovery_queries = build_discovery_queries(title=title, author=author, isbn=isbn, query=query)
    candidates: list[dict[str, Any]] = []

    # 1. Google Custom Search (if credentials provided)
    if api_key and cx and discovery_queries:
        discovery_status = "no_match"
        for discovery_query in discovery_queries:
            g_cands, g_status = await query_google_custom_search(client, discovery_query, api_key, cx)
            candidates.extend(g_cands)
            if g_status == "success":
                discovery_status = "success"
            elif g_status in {"rate_limited", "unavailable"} and discovery_status == "no_match":
                discovery_status = g_status
        if status is not None:
            status["Google Web Discovery"] = discovery_status
    else:
        if status is not None:
            status["Google Web Discovery"] = "not_configured"

    # 2. Open Malayalam Repositories (Wikisource) as supplementary open source
    search_term = title or query or author or ""
    if search_term and not isbn:
        wiki_cands = await query_malayalam_wikisource(client, search_term)
        candidates.extend(wiki_cands)
        if candidates and status is not None and status.get("Google Web Discovery") == "not_configured":
            status["Google Web Discovery"] = "success"

    # Deduplicate candidates by title and author
    unique: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for cand in candidates:
        key = (cand.get("title") or "").strip().lower()
        if key and key not in seen_titles:
            seen_titles.add(key)
            unique.append(cand)

    _save_to_cache(cache_key, unique)
    return unique
