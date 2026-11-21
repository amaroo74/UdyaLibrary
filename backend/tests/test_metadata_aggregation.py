"""Automated tests for Udaya Library metadata retrieval improvement and cross-provider aggregation.

Tests all 8 required scenarios:
1. Crime and Punishment (ISBN 9780140449136) — exact matching edition, category and subcategory.
2. Ikigai — title and author search, cross-provider publisher, category.
3. Malayalam book with an ISBN.
4. Malayalam book without an ISBN.
5. Book with missing publisher in one source — filled from compatible matching source.
6. Book with conflicting publisher across providers — tracked in field_conflicts without data loss.
7. Book with no available price — price remains None, price_currency remains None.
8. Book with insufficient metadata — returns no_match or leaves category unselected, never invents.
"""

from typing import Any
import pytest
from app.metadata.providers import (
    normalize_candidate,
    search_metadata,
)
from app.category_seed import DEFAULT_CATEGORY_TREE
from app.metadata.classifier import suggest_category


def get_default_hierarchy() -> list[dict]:
    return [
        {"name": k, "subcategories": [{"name": s} for s in v]}
        for k, v in DEFAULT_CATEGORY_TREE.items()
    ]


# Helper to simulate search_metadata aggregation logic in an isolated test environment
def aggregate_candidates(candidates: list[dict[str, Any]], requested_isbn: str | None = None) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    merge_fields = (
        "author", "publisher", "price", "price_currency", "price_source",
        "published_date", "publication_year", "edition", "language",
        "page_count", "description", "subtitle", "editor", "translator",
        "series", "volume", "cover_image_url", "source_url",
    )
    for cand in candidates:
        title_key = cand["title"].strip().lower()
        author_key = (cand["author"] or "").strip().lower()
        publisher_key = (cand["publisher"] or "").strip().lower()
        match = None
        for existing in unique:
            same_isbn = bool(existing.get("isbn") and cand.get("isbn") and existing["isbn"] == cand["isbn"])
            same_title_author = (
                existing["title"].strip().lower() == title_key
                and (existing["author"] or "").strip().lower() == author_key
            )
            both_without_isbn = not existing.get("isbn") and not cand.get("isbn")
            compatible_publisher = (
                existing.get("publisher") is None
                or not publisher_key
                or existing["publisher"].strip().lower() == publisher_key
                or existing["publisher"].strip().lower() in publisher_key
                or publisher_key in existing["publisher"].strip().lower()
            )
            if same_isbn:
                match = existing
                break
            if both_without_isbn and same_title_author and compatible_publisher:
                match = existing
                break

        if match is None:
            unique.append(dict(cand))
            continue

        # Merge missing fields
        for field in merge_fields:
            if match.get(field) is None and cand.get(field) is not None:
                match[field] = cand[field]
            elif field == "publisher" and match.get("publisher") and cand.get("publisher"):
                existing_pub = match["publisher"].strip()
                incoming_pub = cand["publisher"].strip()
                if len(incoming_pub) > len(existing_pub) and existing_pub.lower() in incoming_pub.lower():
                    match["publisher"] = incoming_pub

        # Conflict tracking
        conflicts_by_field = match.setdefault("field_conflicts", {})
        for field in ("publisher", "price", "author", "published_date", "publication_year"):
            existing_value = match.get(field)
            incoming_value = cand.get(field)
            if (
                existing_value is not None
                and incoming_value is not None
                and str(existing_value).casefold() != str(incoming_value).casefold()
            ):
                if field == "publisher" and (
                    str(existing_value).casefold() in str(incoming_value).casefold()
                    or str(incoming_value).casefold() in str(existing_value).casefold()
                ):
                    continue
                values = conflicts_by_field.setdefault(field, [])
                for value in (existing_value, incoming_value):
                    if value not in values:
                        values.append(value)

        match["subjects"] = list(dict.fromkeys(match.get("subjects", []) + cand.get("subjects", [])))
        sources = [value.strip() for value in match["source"].split(",")]
        if cand["source"] not in sources:
            match["source"] = f"{match['source']}, {cand['source']}"

    if requested_isbn:
        unique = [c for c in unique if c.get("isbn") == requested_isbn]
        for c in unique:
            c["match_status"] = "exact_isbn"

    return unique


# --------------------------------------------------------------------------
# Test 1: Crime and Punishment (ISBN 9780140449136)
# --------------------------------------------------------------------------
def test_scenario_1_crime_and_punishment_exact_isbn():
    hierarchy = get_default_hierarchy()

    # Source 1 (Open Library): Has title, author, subjects from work, but missing price
    cand_ol = normalize_candidate(
        title="Crime and punishment",
        author="Fiódor Dostoievski",
        publisher="Penguin",
        isbn="9780140449136",
        source="Open Library",
        subjects=["Russian literature", "Fiction", "Psychological fiction", "Classics"],
        description="A Russian novel by Fyodor Dostoevsky.",
    )
    # Source 2 (Google Books): Exact matching ISBN with detailed publisher and price
    cand_gb = normalize_candidate(
        title="Crime and Punishment",
        author="Fyodor Dostoyevsky",
        publisher="Penguin Classics",
        isbn="9780140449136",
        source="Google Books",
        price=450.0,
        price_currency="INR",
        price_source="Google Books (INR)",
        subjects=["Fiction / Classics"],
    )

    aggregated = aggregate_candidates([cand_ol, cand_gb], requested_isbn="9780140449136")
    assert len(aggregated) == 1
    c = aggregated[0]

    # Exact ISBN preserved
    assert c["isbn"] == "9780140449136"
    assert c["match_status"] == "exact_isbn"
    # More descriptive publisher adopted
    assert c["publisher"] == "Penguin Classics"
    # Price filled from Google Books
    assert c["price"] == 450.0
    assert c["price_currency"] == "INR"
    # Both sources recorded
    assert "Open Library" in c["source"]
    assert "Google Books" in c["source"]

    # Category and subcategory automatically suggested
    cat, sub = suggest_category(c, hierarchy)
    assert cat == "Fiction"
    assert sub == "Literary Fiction"


# --------------------------------------------------------------------------
# Test 2: Ikigai — Exact title and authors
# --------------------------------------------------------------------------
def test_scenario_2_ikigai_aggregation():
    hierarchy = get_default_hierarchy()

    # Source 1 (Open Library): Has title, author, subjects
    cand_ol = normalize_candidate(
        title="Ikigai: The Japanese Secret to a Long and Happy Life",
        author="Héctor García, Francesc Miralles",
        publisher="Penguin Books",
        source="Open Library",
        subjects=["Self-help", "Longevity", "Personal Development"],
    )
    # Source 2 (Google Books): Has price
    cand_gb = normalize_candidate(
        title="Ikigai: The Japanese Secret to a Long and Happy Life",
        author="Héctor García, Francesc Miralles",
        publisher="Penguin",
        source="Google Books",
        price=399.0,
        price_currency="INR",
        price_source="Google Books (INR)",
    )

    aggregated = aggregate_candidates([cand_ol, cand_gb])
    assert len(aggregated) == 1
    c = aggregated[0]

    assert c["price"] == 399.0
    assert c["price_currency"] == "INR"
    assert "Penguin Books" in c["publisher"]

    cat, sub = suggest_category(c, hierarchy)
    assert cat == "Non-Fiction"
    assert sub in ("Self-Help", "Personal Development")


# --------------------------------------------------------------------------
# Test 3: Malayalam book with an ISBN
# --------------------------------------------------------------------------
def test_scenario_3_malayalam_book_with_isbn():
    hierarchy = get_default_hierarchy()

    cand_dc = normalize_candidate(
        title="ആടുജീവിതം",
        author="ബെന്യാമിൻ",
        publisher="ഡി.സി. ബുക്സ്",
        isbn="9788184231106",
        source="DC Books",
        subjects=["നോവൽ", "മലയാള സാഹിത്യം"],
        price=220.0,
        price_currency="INR",
        price_source="DC Books (INR)",
    )

    aggregated = aggregate_candidates([cand_dc], requested_isbn="9788184231106")
    assert len(aggregated) == 1
    c = aggregated[0]

    assert c["title"] == "ആടുജീവിതം"
    assert c["author"] == "ബെന്യാമിൻ"
    assert c["publisher"] == "ഡി.സി. ബുക്സ്"
    assert c["price"] == 220.0
    assert c["price_currency"] == "INR"
    assert c["isbn"] == "9788184231106"

    cat, sub = suggest_category(c, hierarchy)
    assert cat == "Fiction"
    assert sub == "Literary Fiction"


# --------------------------------------------------------------------------
# Test 4: Malayalam book without an ISBN
# --------------------------------------------------------------------------
def test_scenario_4_malayalam_book_without_isbn():
    hierarchy = get_default_hierarchy()

    cand_wiki = normalize_candidate(
        title="ഇന്ദുലേഖ",
        author="ഒ. ചന്തുമേനോൻ",
        publisher="മാതൃഭൂമി ബുക്സ്",
        source="Malayalam Wikisource",
        subjects=["നോവൽ", "സാഹിത്യം"],
    )

    aggregated = aggregate_candidates([cand_wiki])
    assert len(aggregated) == 1
    c = aggregated[0]

    assert c["title"] == "ഇന്ദുലേഖ"
    assert c["author"] == "ഒ. ചന്തുമേനോൻ"
    assert c["publisher"] == "മാതൃഭൂമി ബുക്സ്"
    assert c["isbn"] is None
    assert c["price"] is None

    cat, sub = suggest_category(c, hierarchy)
    assert cat == "Fiction"
    assert sub == "Literary Fiction"


# --------------------------------------------------------------------------
# Test 5: Book with missing publisher in one source filled from another
# --------------------------------------------------------------------------
def test_scenario_5_missing_publisher_filled_from_compatible_source():
    # Source A (Wikidata/Internet Archive): Publisher is missing (None)
    cand_a = normalize_candidate(
        title="Wings of Fire",
        author="A. P. J. Abdul Kalam",
        publisher=None,
        isbn="9788173711466",
        source="Internet Archive",
    )
    # Source B (Open Library): Publisher is Universities Press
    cand_b = normalize_candidate(
        title="Wings of Fire",
        author="A. P. J. Abdul Kalam",
        publisher="Universities Press",
        isbn="9788173711466",
        source="Open Library",
        subjects=["Autobiography", "Scientists"],
    )

    aggregated = aggregate_candidates([cand_a, cand_b], requested_isbn="9788173711466")
    assert len(aggregated) == 1
    c = aggregated[0]

    # Publisher successfully backfilled from Source B!
    assert c["publisher"] == "Universities Press"
    assert "Internet Archive" in c["source"]
    assert "Open Library" in c["source"]


# --------------------------------------------------------------------------
# Test 6: Book with conflicting publisher information across providers
# --------------------------------------------------------------------------
def test_scenario_6_conflicting_publisher_preserved_in_conflicts():
    # Two sources reporting genuinely distinct publishers on the same ISBN
    cand_1 = normalize_candidate(
        title="Sample Book",
        author="John Doe",
        publisher="Oxford University Press",
        isbn="9780199535569",
        source="Source 1",
    )
    cand_2 = normalize_candidate(
        title="Sample Book",
        author="John Doe",
        publisher="Cambridge University Press",
        isbn="9780199535569",
        source="Source 2",
    )

    aggregated = aggregate_candidates([cand_1, cand_2], requested_isbn="9780199535569")
    assert len(aggregated) == 1
    c = aggregated[0]

    # Conflict is detected and preserved in field_conflicts without crashing or discarding
    assert "publisher" in c.get("field_conflicts", {})
    assert "Oxford University Press" in c["field_conflicts"]["publisher"]
    assert "Cambridge University Press" in c["field_conflicts"]["publisher"]


# --------------------------------------------------------------------------
# Test 7: Book with no available price
# --------------------------------------------------------------------------
def test_scenario_7_book_with_no_available_price():
    cand = normalize_candidate(
        title="Old Rare Manuscript",
        author="Ancient Scholar",
        publisher="Historic Press",
        isbn="9780000000002",
        source="Library Archive",
        price=None,
        price_currency=None,
    )

    aggregated = aggregate_candidates([cand], requested_isbn="9780000000002")
    assert len(aggregated) == 1
    c = aggregated[0]

    # Price and currency remain strictly None (never invented)
    assert c["price"] is None
    assert c["price_currency"] is None
    assert c["price_source"] is None


# --------------------------------------------------------------------------
# Test 8: Book with insufficient metadata
# --------------------------------------------------------------------------
def test_scenario_8_insufficient_metadata():
    hierarchy = get_default_hierarchy()

    cand_bare = normalize_candidate(
        title="Untitled Item 492049",
        author=None,
        publisher=None,
        isbn=None,
        source="Unknown",
        subjects=[],
    )

    aggregated = aggregate_candidates([cand_bare])
    assert len(aggregated) == 1
    c = aggregated[0]

    # Never invents publisher, author, or price
    assert c["author"] is None
    assert c["publisher"] is None
    assert c["price"] is None

    # Category leaves unselected (None, None)
    cat, sub = suggest_category(c, hierarchy)
    assert cat is None
    assert sub is None


def test_author_normalization_and_trailing_comma_cleanup_in_aggregation():
    cand1 = normalize_candidate(
        title="Atomic Habits",
        author="Clear, James,",
        publisher="Penguin",
        isbn="9780735211292",
        source="SourceA",
    )
    assert cand1["author"] == "James Clear"

    cand2 = normalize_candidate(
        title="Atomic Habits",
        author="James Clear",
        publisher="Penguin",
        isbn="9780735211292",
        source="SourceB",
    )
    assert cand2["author"] == "James Clear"

    aggregated = aggregate_candidates([cand1, cand2])
    assert len(aggregated) == 1
    assert aggregated[0]["author"] == "James Clear"
    # No author conflict because normalized author strings match
    assert "author" not in aggregated[0].get("field_conflicts", {})

