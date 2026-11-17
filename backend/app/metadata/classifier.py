import re
from typing import Any


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def suggest_category(
    candidate: dict[str, Any],
    categories: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Suggest an existing category pair only on an exact metadata word match."""
    metadata = " ".join(
        [
            candidate.get("title") or "",
            candidate.get("author") or "",
            candidate.get("publisher") or "",
            " ".join(candidate.get("subjects") or []),
        ]
    )
    metadata_words = _words(metadata)
    matches: list[tuple[int, str, str | None]] = []
    keyword_aliases = {
        "ikigai": ("Non-Fiction", "Self-Help"),
        "self-help": ("Non-Fiction", "Self-Help"),
        "productivity": ("Non-Fiction", "Personal Development"),
        "motivation": ("Non-Fiction", "Personal Development"),
        "mindfulness": ("Non-Fiction", "Personal Development"),
    }

    for keyword, (category_name, subcategory_name) in keyword_aliases.items():
        if _words(keyword) <= metadata_words:
            for category in categories:
                if category.get("name") != category_name:
                    continue
                if any(
                    subcategory.get("name") == subcategory_name
                    for subcategory in category.get("subcategories", [])
                ):
                    matches.append((3, category_name, subcategory_name))

    for category in categories:
        category_name = category.get("name", "")
        category_words = _words(category_name)
        if category_words and category_words <= metadata_words:
            matches.append((len(category_words), category_name, None))
        for subcategory in category.get("subcategories", []):
            sub_name = subcategory.get("name", "")
            sub_words = _words(sub_name)
            if sub_words and sub_words <= metadata_words:
                matches.append((len(sub_words) + 1, category_name, sub_name))

    if not matches:
        return None, None
    _, category_name, subcategory_name = max(matches, key=lambda item: item[0])
    return category_name, subcategory_name
