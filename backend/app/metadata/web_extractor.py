"""Structured webpage bibliographic metadata extractor.

Extracts Schema.org JSON-LD, Open Graph, Dublin Core, and standard HTML metadata
from permitted web pages into Udaya Library candidate format.
"""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from ..isbn import clean_isbn, normalize_isbn
from .malayalam_normalizer import normalize_malayalam_text
from .providers import normalize_candidate

logger = logging.getLogger(__name__)

# Regular expressions for metadata extraction without heavy external dependencies
JSON_LD_REGEX = re.compile(
    r'<script[^>]*?type=[\'"]application/ld\+json[\'"][^>]*?>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
META_TAG_REGEX = re.compile(
    r'<meta\s+([^>]*?)(?:/?>)',
    re.DOTALL | re.IGNORECASE,
)
TITLE_TAG_REGEX = re.compile(
    r'<title[^>]*?>(.*?)</title>',
    re.DOTALL | re.IGNORECASE,
)
ATTR_REGEX = re.compile(
    r'([a-zA-Z0-9_\-\.:]+)\s*=\s*[\'"]([^\'"]*?)[\'"]'
)


def _clean_catalogue_title(title: str, author: str | None, publisher: str | None) -> str:
    """Remove common catalogue/year decoration without changing Unicode titles."""
    cleaned = re.sub(r"^\s*(?:19|20)\d{2}\s*[:|\-–—]\s*", "", title).strip()
    parts = re.split(r"\s+[|]\s+", cleaned, maxsplit=1)
    if len(parts) == 2:
        cleaned = parts[0].strip()
    for suffix in (author, publisher):
        if suffix and re.search(rf"\s+[-–—]\s+{re.escape(suffix)}\s*$", cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(rf"\s+[-–—]\s+{re.escape(suffix)}\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _parse_meta_attributes(tag_content: str) -> dict[str, str]:
    """Parse key-value attributes from an HTML meta tag string."""
    attrs: dict[str, str] = {}
    for match in ATTR_REGEX.finditer(tag_content):
        attrs[match.group(1).lower()] = match.group(2).strip()
    return attrs


def _extract_name_or_string(value: Any) -> str | None:
    """Extract a name string from a dict, list, or primitive value."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        name = value.get("name") or value.get("legalName") or value.get("title")
        if isinstance(name, str):
            return name.strip() or None
    if isinstance(value, list):
        names = []
        for item in value:
            extracted = _extract_name_or_string(item)
            if extracted:
                names.append(extracted)
        return ", ".join(names) if names else None
    return None


def _extract_price(offers: Any) -> tuple[float | None, str | None]:
    """Extract price amount and currency code from Schema.org offers."""
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        raw_price = offers.get("price") or offers.get("lowPrice")
        currency = offers.get("priceCurrency")
        if raw_price is not None:
            try:
                # Remove currency symbols or commas
                cleaned = re.sub(r"[^\d\.]", "", str(raw_price))
                if cleaned:
                    val = float(cleaned)
                    curr = str(currency).strip().upper() if currency else "INR"
                    return (val, curr)
            except (ValueError, TypeError):
                pass
    return (None, None)


def _extract_isbn(item: dict[str, Any]) -> str | None:
    """Extract ISBN-10 or ISBN-13 from common Schema.org keys."""
    for key in ("isbn", "gtin13", "gtin14", "gtin", "identifier"):
        val = item.get(key)
        if isinstance(val, str):
            cleaned = clean_isbn(val)
            if cleaned and len(cleaned) in (10, 13):
                return normalize_isbn(cleaned)
        elif isinstance(val, list):
            for sub in val:
                sub_isbn = _extract_isbn({"isbn": sub})
                if sub_isbn:
                    return sub_isbn
        elif isinstance(val, dict):
            sub_isbn = _extract_isbn(val)
            if sub_isbn:
                return sub_isbn
    return None


def extract_json_ld_candidates(html: str, source_url: str) -> list[dict[str, Any]]:
    """Extract bibliographic records from Schema.org JSON-LD scripts."""
    candidates: list[dict[str, Any]] = []
    domain = urlparse(source_url).netloc or "Web Discovery"

    for script_match in JSON_LD_REGEX.finditer(html):
        script_text = script_match.group(1).strip()
        if not script_text:
            continue
        try:
            data = json.loads(script_text)
        except json.JSONDecodeError:
            continue

        # Flatten @graph or lists
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items.extend([i for i in data if isinstance(i, dict)])
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                items.extend([i for i in data["@graph"] if isinstance(i, dict)])
            else:
                items.append(data)

        for item in items:
            raw_type = item.get("@type")
            types = set()
            if isinstance(raw_type, str):
                types.add(raw_type.lower())
            elif isinstance(raw_type, list):
                types.update(str(t).lower() for t in raw_type)

            # Accept Book, Product, CreativeWork, IndividualProduct
            if not types.intersection({"book", "product", "individualproduct", "creativework", "publicationvolume"}):
                continue

            raw_title = item.get("name") or item.get("headline") or item.get("title")
            title = _extract_name_or_string(raw_title)
            if not title:
                continue

            author = _extract_name_or_string(item.get("author") or item.get("creator"))
            publisher = _extract_name_or_string(item.get("publisher"))
            isbn = _extract_isbn(item)
            price, currency = _extract_price(item.get("offers"))

            published_date = str(item.get("datePublished") or item.get("copyrightYear") or "").strip() or None
            publication_year = None
            if published_date:
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", published_date)
                if year_match:
                    publication_year = int(year_match.group(1))

            description = _extract_name_or_string(item.get("description"))
            language = _extract_name_or_string(item.get("inLanguage"))
            page_count = None
            raw_pages = item.get("numberOfPages")
            if raw_pages is not None:
                try:
                    page_count = int(raw_pages)
                except (ValueError, TypeError):
                    pass

            image_url = item.get("image")
            if isinstance(image_url, list) and image_url:
                image_url = image_url[0]
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            cover_image_url = str(image_url).strip() if image_url else None

            candidate = normalize_candidate(
                title=normalize_malayalam_text(title),
                author=normalize_malayalam_text(author) if author else None,
                publisher=normalize_malayalam_text(publisher) if publisher else None,
                price=price,
                price_currency=currency,
                price_source=domain if price else None,
                source=f"{domain} (Structured Data)",
                isbn=isbn,
                published_date=published_date,
                publication_year=publication_year,
                language=language,
                page_count=page_count,
                description=description,
                cover_image_url=cover_image_url,
            )
            candidate["source_url"] = source_url
            candidate["field_provenance"] = {
                k: [domain] for k, v in candidate.items() if v is not None and not k.startswith("_")
            }
            candidates.append(candidate)

    return candidates


def extract_meta_tags_candidate(html: str, source_url: str) -> dict[str, Any] | None:
    """Extract candidate metadata from Dublin Core, Open Graph, and HTML meta tags."""
    domain = urlparse(source_url).netloc or "Web Discovery"
    meta_tags: dict[str, str] = {}

    for meta_match in META_TAG_REGEX.finditer(html):
        attrs = _parse_meta_attributes(meta_match.group(1))
        name = attrs.get("name") or attrs.get("property") or attrs.get("itemprop")
        content = attrs.get("content") or attrs.get("value")
        if name and content:
            meta_tags[name.lower()] = content.strip()

    title = (
        meta_tags.get("dc.title")
        or meta_tags.get("citation_title")
        or meta_tags.get("og:title")
        or meta_tags.get("twitter:title")
    )

    if not title:
        title_match = TITLE_TAG_REGEX.search(html)
        if title_match:
            title = title_match.group(1).strip()
            # Clean common trailing suffixes e.g. "Book Name | Publisher"
            title = re.sub(r"\s*[\|\-–—]\s*(DC Books|Indulekha|Mathrubhumi|Amazon).*$", "", title, flags=re.I).strip()

    if not title:
        return None

    author = (
        meta_tags.get("dc.creator")
        or meta_tags.get("citation_author")
        or meta_tags.get("author")
        or meta_tags.get("book:author")
    )
    publisher = (
        meta_tags.get("dc.publisher")
        or meta_tags.get("citation_publisher")
        or meta_tags.get("og:site_name")
        or meta_tags.get("publisher")
    )
    title = _clean_catalogue_title(title, author, publisher)
    isbn = (
        meta_tags.get("dc.identifier.isbn")
        or meta_tags.get("citation_isbn")
        or meta_tags.get("book:isbn")
    )
    if isbn:
        isbn = normalize_isbn(clean_isbn(isbn))

    date_str = (
        meta_tags.get("dc.date")
        or meta_tags.get("citation_publication_date")
        or meta_tags.get("citation_date")
        or meta_tags.get("article:published_time")
    )
    publication_year = None
    if date_str:
        year_match = re.search(r"\b(19\d\d|20\d\d)\b", date_str)
        if year_match:
            publication_year = int(year_match.group(1))

    description = (
        meta_tags.get("description")
        or meta_tags.get("og:description")
        or meta_tags.get("dc.description")
    )
    language = meta_tags.get("dc.language") or meta_tags.get("citation_language")
    image_url = meta_tags.get("og:image") or meta_tags.get("twitter:image")

    candidate = normalize_candidate(
        title=normalize_malayalam_text(title),
        author=normalize_malayalam_text(author) if author else None,
        publisher=normalize_malayalam_text(publisher) if publisher else None,
        source=f"{domain} (Meta Tags)",
        isbn=isbn,
        published_date=date_str,
        publication_year=publication_year,
        language=language,
        description=description,
        cover_image_url=image_url,
    )
    candidate["source_url"] = source_url
    candidate["field_provenance"] = {
        k: [domain] for k, v in candidate.items() if v is not None and not k.startswith("_")
    }
    return candidate


def extract_webpage_metadata(html: str, source_url: str) -> list[dict[str, Any]]:
    """
    Extract all available bibliographic candidates from a webpage.
    Prioritizes Schema.org JSON-LD, falling back to Dublin Core / Open Graph.
    """
    # 1. JSON-LD structured data (highest fidelity)
    candidates = extract_json_ld_candidates(html, source_url)
    if candidates:
        return candidates

    # 2. Meta tags fallback (Dublin Core / Open Graph / HTML)
    meta_cand = extract_meta_tags_candidate(html, source_url)
    if meta_cand:
        return [meta_cand]

    return []
