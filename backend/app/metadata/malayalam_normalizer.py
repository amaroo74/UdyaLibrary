"""Malayalam Unicode text normalization, chillu harmonization, and phonetic matching utilities."""

import re
import unicodedata

# Malayalam Unicode block: U+0D00 - U+0D7F
MALAYALAM_RANGE_REGEX = re.compile(r"[\u0D00-\u0D7F]")

# Chillu harmonization: legacy consonant + virama + ZWJ -> modern atomic chillu
CHILLU_MAPPINGS = [
    ("\u0D23\u0D4D\u200D", "\u0D7A"),  # ൺ (nn)
    ("\u0D28\u0D4D\u200D", "\u0D7B"),  # ൻ (n)
    ("\u0D30\u0D4D\u200D", "\u0D7C"),  # ർ (r)
    ("\u0D32\u0D4D\u200D", "\u0D7D"),  # ൽ (l)
    ("\u0D33\u0D4D\u200D", "\u0D7E"),  # ൾ (ll)
    ("\u0D15\u0D4D\u200D", "\u0D7F"),  # ൿ (k)
]

# Basic phonetic mapping from Malayalam characters to Latin/English script
MALAYALAM_TO_LATIN = {
    "അ": "a", "ആ": "aa", "ഇ": "i", "ഈ": "ee", "ഉ": "u", "ഊ": "oo",
    "ഋ": "ri", "എ": "e", "ഏ": "e", "ഐ": "ai", "ഒ": "o", "ഓ": "o", "ഔ": "au",
    "ക": "ka", "ഖ": "kha", "ഗ": "ga", "ഘ": "gha", "ങ": "nga",
    "ച": "cha", "ഛ": "chha", "ജ": "ja", "ഝ": "jha", "ഞ": "nya",
    "ട": "ta", "ഠ": "tha", "ഡ": "da", "ഢ": "dha", "ണ": "na",
    "ത": "tha", "ഥ": "thha", "ദ": "da", "ധ": "dha", "ന": "na",
    "പ": "pa", "ഫ": "pha", "ബ": "ba", "ഭ": "bha", "മ": "ma",
    "യ": "ya", "ര": "ra", "ല": "la", "വ": "va", "ശ": "sha",
    "ഷ": "sha", "സ": "sa", "ഹ": "ha", "ള": "la", "ഴ": "zha", "റ": "ra",
    "ൺ": "n", "ൻ": "n", "ർ": "r", "ൽ": "l", "ൾ": "l", "ൿ": "k",
    "ാ": "aa", "ി": "i", "ീ": "ee", "ു": "u", "ൂ": "oo", "ൃ": "ri",
    "െ": "e", "േ": "e", "ൈ": "ai", "ൊ": "o", "ോ": "o", "ൌ": "au",
    "ം": "m", "ഃ": "h", "്": "",
}


def is_malayalam(text: str | None) -> bool:
    """Return True if text contains at least one Malayalam character."""
    if not text:
        return False
    return bool(MALAYALAM_RANGE_REGEX.search(text))


def normalize_chillu(text: str) -> str:
    """Harmonize legacy ZWJ chillu sequences to modern atomic chillu characters."""
    if not text:
        return ""
    normalized = text
    for pattern, replacement in CHILLU_MAPPINGS:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def normalize_malayalam_text(text: str | None) -> str:
    """
    Standardize Malayalam Unicode without destroying or discarding original text.
    Applies Unicode NFC normalization, collapses whitespace, and harmonizes chillus.
    """
    if not text:
        return ""
    # 1. Unicode NFC normalization
    normalized = unicodedata.normalize("NFC", text)
    # 2. Chillu harmonization
    normalized = normalize_chillu(normalized)
    # 3. Collapse whitespace and strip
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def strip_punctuation_for_matching(text: str | None) -> str:
    """
    Remove punctuation and symbols for loose comparison.
    Retains Malayalam script, English alphanumeric characters, and whitespace.
    """
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s\u0D00-\u0D7F]", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def fuzzy_match_malayalam(left: str | None, right: str | None) -> bool:
    """
    Compare two strings with tolerance for punctuation, initials, and chillu variations.
    Does not modify the original text.
    """
    if left is None or right is None:
        return False

    norm_left = strip_punctuation_for_matching(normalize_malayalam_text(left)).casefold()
    norm_right = strip_punctuation_for_matching(normalize_malayalam_text(right)).casefold()

    if not norm_left or not norm_right:
        return False

    if norm_left == norm_right:
        return True

    # Whitespace-insensitive match (handles compound words like ബാല്യകാലസഖി vs ബാല്യകാല സഖി)
    if norm_left.replace(" ", "") == norm_right.replace(" ", ""):
        return True

    # Token-set overlap comparison (handles initials and reversed name order)
    tokens_left = set(norm_left.split())
    tokens_right = set(norm_right.split())
    if tokens_left == tokens_right:
        return True

    # If one is a complete subset of the other with length >= 2 words
    if len(tokens_left) >= 2 and tokens_left.issubset(tokens_right):
        return True
    if len(tokens_right) >= 2 and tokens_right.issubset(tokens_left):
        return True

    return False


def transliterate_malayalam_to_latin(text: str | None) -> str:
    """
    Phonetically transliterate Malayalam characters to Latin/English script for dual search.
    Preserves existing ASCII characters.
    """
    if not text:
        return ""
    normalized = normalize_malayalam_text(text)
    result = []
    i = 0
    chars = list(normalized)
    while i < len(chars):
        char = chars[i]
        if char in MALAYALAM_TO_LATIN:
            val = MALAYALAM_TO_LATIN[char]
            # Check for vowel signs following consonants
            if i + 1 < len(chars) and chars[i + 1] in {"ാ", "ി", "ീ", "ു", "ൂ", "ൃ", "െ", "േ", "ൈ", "ൊ", "ോ", "ൌ", "്"}:
                vowel_sign = chars[i + 1]
                vowel_val = MALAYALAM_TO_LATIN.get(vowel_sign, "")
                base_val = val[:-1] if val.endswith("a") else val
                result.append(base_val + vowel_val)
                i += 2
                continue
            result.append(val)
        else:
            result.append(char)
        i += 1
    return "".join(result).strip()


def build_discovery_queries(
    title: str | None = None,
    author: str | None = None,
    isbn: str | None = None,
    query: str | None = None,
) -> list[str]:
    """
    Build prioritized search query strings.
    If Malayalam text is detected, generates both Unicode and Latin transliterations.
    """
    queries: list[str] = []

    # 1. Exact ISBN query
    if isbn:
        clean = re.sub(r"[^\dXx]", "", isbn)
        if clean:
            queries.append(f"isbn {clean}")
            queries.append(clean)
            return queries

    clean_title = normalize_malayalam_text(title)
    clean_author = normalize_malayalam_text(author)
    clean_query = normalize_malayalam_text(query)

    # 2. Malayalam title and author combined
    if clean_title and clean_author:
        queries.append(f'"{clean_title}" "{clean_author}"')
        queries.append(f"{clean_title} {clean_author}")
    elif clean_title and is_malayalam(clean_title):
        queries.append(f'"{clean_title}"')
        queries.append(f"{clean_title} പുസ്തകം")  # "pusthakam" (book in Malayalam)
    elif clean_title:
        queries.append(f'"{clean_title}"')
    elif clean_author:
        queries.append(f'"{clean_author}" പുസ്തകങ്ങൾ')
    elif clean_query:
        queries.append(clean_query)

    # 3. Transliteration assistance for Malayalam queries
    if clean_title and is_malayalam(clean_title):
        latin_title = transliterate_malayalam_to_latin(clean_title)
        if latin_title and latin_title != clean_title:
            if clean_author:
                latin_author = transliterate_malayalam_to_latin(clean_author) if is_malayalam(clean_author) else clean_author
                queries.append(f"{latin_title} {latin_author}")
            else:
                queries.append(f"{latin_title} book")

    # Deduplicate while preserving priority order
    seen = set()
    deduped = []
    for q in queries:
        q_strip = q.strip()
        if q_strip and q_strip.lower() not in seen:
            seen.add(q_strip.lower())
            deduped.append(q_strip)

    return deduped
