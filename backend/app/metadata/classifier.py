"""Automatic category and subcategory classification engine for Udaya Library.

Prioritises:
1. Exact and direct matches with existing library categories and subcategories.
2. External subject metadata mapped to the approved 12-category library hierarchy.
3. Malayalam Unicode literary genre and classification vocabulary.
4. Title, author, and description keyword heuristics.
5. Confidence scoring with strict validation against the library's active hierarchy.
"""

from __future__ import annotations

import re
from typing import Any


def _normalize_tokens(text: str | None) -> set[str]:
    """Extract lowercase alphanumeric tokens from English or Malayalam text."""
    if not text:
        return set()
    # Match both standard alphanumeric and Malayalam Unicode characters
    return set(re.findall(r"[\w\u0D00-\u0D7F]+", text.lower()))


# External Subject / Keyword to (Category, Subcategory) mappings
TAXONOMY_MAP: list[tuple[list[str], str, str | None]] = [
    # --- Fiction: Literary Fiction ---
    (
        [
            "classics", "classic literature", "russian literature", "literary fiction",
            "world literature", "modern classics", "classic fiction", "fiction classics",
            "dostoevsky", "dostoievski", "tolstoy", "chekhov", "turgenev", "franz kafka",
            "george orwell", "charles dickens", "jane austen", "bronte", "victor hugo",
            "flaubert", "hemingway", "fitzgerald", "james joyce", "virginia woolf",
            "gabriel garcia marquez", "salman rushdie", "arundhati roy", "r.k. narayan",
            "rabindranath tagore", "jhumpa lahiri", "amitav ghosh", "anita desai",
            "crime and punishment", "war and peace", "brothers karamazov", "anna karenina",
            "pride and prejudice", "great gatsby", "1984", "animal farm",
            # Malayalam literary classics and novelists
            "നോവൽ", "ആഖ്യായിക", "ക്ലാസിക്", "ഖസാക്കിന്റെ ഇതിഹാസം", "ഇന്ദുലേഖ",
            "രണ്ടാമൂഴം", "ചെമ്മീൻ", "ബാല്യകാലസഖി", "പാത്തുമ്മായുടെ ആട്", "ആടുജീവിതം",
            "ബഷീർ", "തകഴി", "എം ടി", "വാസുദേവൻ നായർ", "ഒ വി വിജയൻ", "മാധവിക്കുട്ടി",
            "ഉറൂബ്", "പൊറ്റെക്കാട്ട്", "പത്മനാഭൻ", "മുകുന്ദൻ", "സക്കറിയ", "ആനന്ദ്",
            "സേതു", "പുനത്തിൽ", "കെ ആർ മീര", "ബെന്യാമിൻ", "സുഭാഷ് ചന്ദ്രൻ",
        ],
        "Fiction",
        "Literary Fiction",
    ),
    # --- Fiction: Mystery & Crime ---
    (
        [
            "mystery", "mysteries", "mystery fiction", "detective", "detective fiction",
            "crime fiction", "murder mystery", "investigation", "whodunit", "police procedural",
            "sherlock holmes", "agatha christie", "poirot", "conan doyle",
            "ഡിറ്റക്ടീവ്", "കുറ്റാന്വേഷണം", "രഹസ്യം",
        ],
        "Fiction",
        "Mystery",
    ),
    # --- Fiction: Thriller ---
    (
        [
            "thriller", "suspense", "psychological thriller", "legal thriller", "spy thriller",
            "espionage", "action fiction", "adventure fiction", "psychological fiction",
            "ത്രില്ലർ", "സാഹസികം",
        ],
        "Fiction",
        "Thriller",
    ),
    # --- Fiction: Romance ---
    (
        [
            "romance", "romantic", "love story", "romantic fiction", "contemporary romance",
            "historical romance", "പ്രണയം", "പ്രണയകഥ",
        ],
        "Fiction",
        "Romance",
    ),
    # --- Fiction: Fantasy ---
    (
        [
            "fantasy", "epic fantasy", "magic", "science fiction", "sci-fi", "scifi",
            "space opera", "dystopian", "tolkien", "harry potter", "rowling",
            "ഫാന്റസി", "സയൻസ് ഫിക്ഷൻ",
        ],
        "Fiction",
        "Fantasy",
    ),
    # --- Fiction: Historical Fiction ---
    (
        [
            "historical fiction", "historical novel", "period drama", "war novel",
            "ചരിത്ര നോവൽ", "ഐതിഹ്യമാല",
        ],
        "Fiction",
        "Historical Fiction",
    ),
    # --- Non-Fiction: Self-Help ---
    (
        [
            "self-help", "self help", "ikigai", "personal growth", "self improvement",
            "habits", "atomic habits", "time management", "counseling", "mindset",
            "വ്യക്തിത്വ വികസനം", "ജീവിതവിജയം", "സ്വയംസഹായം",
        ],
        "Non-Fiction",
        "Self-Help",
    ),
    # --- Non-Fiction: Personal Development ---
    (
        [
            "personal development", "productivity", "motivation", "motivational",
            "leadership", "success", "mindfulness", "goal setting", "career",
            "wealth", "financial freedom", "നേതൃത്വം",
        ],
        "Non-Fiction",
        "Personal Development",
    ),
    # --- Non-Fiction: Psychology ---
    (
        [
            "psychology", "psychological", "behavioral", "cognition", "mental health",
            "psychoanalysis", "freud", "carl jung", "human behavior",
            "മനശാസ്ത്രം", "മനഃശാസ്ത്രം",
        ],
        "Non-Fiction",
        "Psychology",
    ),
    # --- Non-Fiction: Philosophy ---
    (
        [
            "philosophy", "philosophical", "ethics", "existentialism", "stoicism",
            "epistemology", "nietzsche", "plato", "aristotle", "kant", "socrates",
            "തത്ത്വചിന്ത", "ദർശനം",
        ],
        "Non-Fiction",
        "Philosophy",
    ),
    # --- Non-Fiction: General Knowledge ---
    (
        [
            "general knowledge", "gk", "trivia", "facts", "quizzing", "quiz",
            "yearbook", "manorama yearbook", "പൊതുവിജ്ഞാനം", "വിജ്ഞാനം",
        ],
        "Non-Fiction",
        "General Knowledge",
    ),
    # --- Science ---
    (
        ["physics", "quantum", "mechanics", "relativity", "einstein", "feynman", "ഭൗതികശാസ്ത്രം"],
        "Science",
        "Physics",
    ),
    (
        ["chemistry", "organic chemistry", "inorganic chemistry", "biochemistry", "chemical", "രസതന്ത്രം"],
        "Science",
        "Chemistry",
    ),
    (
        ["biology", "botany", "zoology", "genetics", "evolution", "dna", "darwin", "ജീവശാസ്ത്രം", "സസ്യശാസ്ത്രം", "ജന്തുശാസ്ത്രം"],
        "Science",
        "Biology",
    ),
    (
        ["mathematics", "math", "algebra", "calculus", "geometry", "statistics", "probability", "ഗണിതം", "ഗണിതശാസ്ത്രം"],
        "Science",
        "Mathematics",
    ),
    (
        ["astronomy", "astrophysics", "cosmos", "space", "planets", "stars", "stephen hawking", "carl sagan", "ജ്യോതിശാസ്ത്രം", "ബഹിരാകാശം"],
        "Science",
        "Astronomy",
    ),
    (
        ["environment", "environmental", "ecology", "ecological", "climate change", "conservation", "പരിസ്ഥിതി", "പ്രകൃതി"],
        "Science",
        "Environment",
    ),
    # --- Technology & Engineering ---
    (
        ["computer science", "programming", "software", "coding", "algorithms", "web development", "python", "javascript", "കമ്പ്യൂട്ടർ"],
        "Technology & Engineering",
        "Computer Science",
    ),
    (
        ["artificial intelligence", "machine learning", "deep learning", "robotics", "automation", "നിർമ്മിത ബുദ്ധി"],
        "Technology & Engineering",
        "Artificial Intelligence & Robotics",
    ),
    (
        ["electronics", "circuits", "semiconductors", "microprocessors", "ഇലക്ട്രോണിക്സ്"],
        "Technology & Engineering",
        "Electronics",
    ),
    (
        ["electrical engineering", "power systems", "high voltage", "വൈദ്യുതി"],
        "Technology & Engineering",
        "Electrical Engineering",
    ),
    (
        ["mechanical engineering", "thermodynamics", "automotive", "മെക്കാനിക്കൽ"],
        "Technology & Engineering",
        "Mechanical Engineering",
    ),
    (
        ["civil engineering", "structures", "surveying", "concrete", "സിവിൽ എൻജിനീയറിംഗ്"],
        "Technology & Engineering",
        "Civil Engineering",
    ),
    # --- History & Geography ---
    (
        ["kerala history", "history of kerala", "travancore", "cochin", "malabar", "sree narayana guru", "ayyankali", "കേരള ചരിത്രം", "ചരിത്രം"],
        "History & Geography",
        "Kerala History",
    ),
    (
        ["indian history", "india history", "freedom struggle", "gandhi", "nehru", "mughal", "british raj", "ഇന്ത്യൻ ചരിത്രം", "സ്വാതന്ത്ര്യസമരം"],
        "History & Geography",
        "Indian History",
    ),
    (
        ["world history", "world war", "wwi", "wwii", "civilization", "roman empire", "ലോക ചരിത്രം"],
        "History & Geography",
        "World History",
    ),
    (
        ["geography", "maps", "continents", "oceanography", "ഭൂമിശാസ്ത്രം"],
        "History & Geography",
        "Geography",
    ),
    (
        ["politics", "political science", "democracy", "constitution", "government", "രാഷ്ട്രീയം", "ഭരണഘടന"],
        "History & Geography",
        "Politics",
    ),
    # --- Biography & Autobiography ---
    (
        ["biography", "autobiography", "memoir", "memoirs", "life of", "diaries", "ജീവചരിത്രം", "ആത്മകഥ", "സ്മരണകൾ", "ഓർമ്മക്കുറിപ്പുകൾ"],
        "Biography & Autobiography",
        "Other Personalities",
    ),
    # --- Literature ---
    (
        ["poetry", "poems", "poet", "verses", "sonnets", "കവിത", "കവിതകൾ", "കവി", "പദ്യങ്ങൾ", "കുമാരനാശാൻ", "വള്ളത്തോൾ", "ഉള്ളൂർ", "ചങ്ങമ്പുഴ", "വയലാർ", "ഒ എൻ വി"],
        "Literature",
        "Poetry",
    ),
    (
        ["drama", "plays", "playwright", "theatre", "shakespeare", "നാടകം", "നാടകങ്ങൾ", "തോപ്പിൽ ഭാസി"],
        "Literature",
        "Drama",
    ),
    (
        ["essays", "discourse", "prose", "പ്രബന്ധങ്ങൾ", "ലേഖനങ്ങൾ", "ലേഖനസമാഹാരം"],
        "Literature",
        "Essays",
    ),
    (
        ["literary criticism", "criticism", "poetics", "സാഹിത്യ നിരൂപണം", "നിരൂപണം"],
        "Literature",
        "Literary Criticism",
    ),
    # --- Religion & Spirituality ---
    (
        ["gita", "bhagavad gita", "upanishads", "vedanta", "advaita", "ഭഗവദ്ഗീത", "ഉപനിഷത്ത്", "വേദാന്തം"],
        "Religion & Spirituality",
        "Indian Philosophy",
    ),
    (
        ["spirituality", "spiritual", "meditation", "yoga", "mysticism", "prayer", "ആത്മീയത", "ധ്യാനം", "യോഗ"],
        "Religion & Spirituality",
        "Spirituality",
    ),
    (
        ["comparative religion", "hinduism", "islam", "christianity", "buddhism", "quran", "bible", "മതം"],
        "Religion & Spirituality",
        "Comparative Religion",
    ),
    (
        ["ethics", "moral philosophy", "morality", "ധാർമ്മികത", "സദാചാരം"],
        "Religion & Spirituality",
        "Ethics",
    ),
    # --- Children's Books ---
    (
        ["children", "children's", "juvenile fiction", "bedtime stories", "fairy tales", "panchatantra", "കുട്ടിക്കഥകൾ", "ബാലസാഹിത്യം", "പഞ്ചതന്ത്രം"],
        "Children's Books",
        "Stories",
    ),
    (
        ["comics", "comic strip", "graphic novel", "tintin", "asterix", "amar chitra katha", "balarama", "കോമിക്സ്", "ചിത്രകഥകൾ", "ബാലരമ"],
        "Children's Books",
        "Comics",
    ),
    # --- Language & Linguistics ---
    (
        ["malayalam language", "malayalam grammar", "മലയാളം", "മലയാള ഭാഷ"],
        "Language & Linguistics",
        "Malayalam",
    ),
    (
        ["english language", "grammar", "vocabulary", "വ്യാകരണം"],
        "Language & Linguistics",
        "Grammar",
    ),
    # --- Arts & Culture ---
    (
        ["cinema", "films", "movies", "film studies", "screenplay", "സിനിമ", "ചലച്ചിത്രം", "തിരക്കഥ"],
        "Arts & Culture",
        "Cinema",
    ),
    (
        ["music", "classical music", "carnatic", "raga", "songs", "സംഗീതം", "പാട്ടുകൾ"],
        "Arts & Culture",
        "Music",
    ),
    (
        ["art", "painting", "sculpture", "drawing", "ചിത്രകല", "കല"],
        "Arts & Culture",
        "Art",
    ),
    (
        ["culture", "folklore", "heritage", "kathakali", "theyyam", "സംസ്കാരം", "പൈതൃകം", "കഥകളി"],
        "Arts & Culture",
        "Culture",
    ),
    # High-frequency catalogue titles whose provider subjects are often sparse.
    (
        ["wings of fire", "abdul kalam", "a p j abdul kalam"],
        "Biography & Autobiography",
        "Leaders",
    ),
    (
        ["a brief history of time", "stephen hawking", "cosmology"],
        "Science",
        "Astronomy",
    ),
    (
        ["the alchemist", "paulo coelho"],
        "Fiction",
        "Literary Fiction",
    ),
]


def _match_phrase(phrase: str, text_lower: str, tokens: set[str]) -> bool:
    """Check if a single or multi-word phrase matches the text."""
    p_lower = phrase.lower().strip()
    if " " in p_lower:
        return p_lower in text_lower
    return p_lower in tokens


def suggest_category(
    candidate: dict[str, Any],
    categories: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """
    Suggest an existing category and subcategory from the library's active hierarchy.

    Prioritises:
    1. Direct match with existing library category and subcategory names.
    2. External subject metadata mapped via taxonomy.
    3. Title, author, and description keyword analysis.
    4. Strict validation: Only returns categories and subcategories that exist in categories.
    5. Returns (None, None) if confidence is low or no valid match is found.
    """
    if not categories:
        return None, None

    # Build hierarchy lookup maps:
    # parent_map: category_name.lower() -> category_name
    # subcategory_map: (category_name.lower(), sub_name.lower()) -> sub_name
    # valid_subs_per_cat: category_name.lower() -> set of sub_name.lower()
    parent_map: dict[str, str] = {}
    subcategory_map: dict[tuple[str, str], str] = {}
    valid_subs_per_cat: dict[str, set[str]] = {}

    for cat in categories:
        c_name = cat.get("name", "").strip()
        if not c_name:
            continue
        c_lower = c_name.lower()
        parent_map[c_lower] = c_name
        valid_subs_per_cat[c_lower] = set()

        for sub in cat.get("subcategories", []):
            s_name = sub.get("name", "").strip()
            if s_name:
                s_lower = s_name.lower()
                subcategory_map[(c_lower, s_lower)] = s_name
                valid_subs_per_cat[c_lower].add(s_lower)

    # Extract metadata fields
    title = str(candidate.get("title") or "").strip()
    author = str(candidate.get("author") or "").strip()
    publisher = str(candidate.get("publisher") or "").strip()
    description = str(candidate.get("description") or "").strip()
    subjects = [
        str(s).strip()
        for s in candidate.get("subjects") or []
        if isinstance(s, (str, int, float)) and str(s).strip()
    ]

    title_lower = title.lower()
    subjects_lower = " ".join(subjects).lower()
    description_lower = description[:1000].lower()
    full_text_lower = f"{title} {author} {publisher} {' '.join(subjects)} {description}".lower()

    title_tokens = _normalize_tokens(title)
    subjects_tokens = _normalize_tokens(" ".join(subjects))
    full_tokens = _normalize_tokens(full_text_lower)

    # Candidate matches: list of (score, category_name, subcategory_name)
    matches: list[tuple[int, str, str | None]] = []

    # -------------------------------------------------------------
    # 1. Direct Hierarchy Match against existing library categories
    # -------------------------------------------------------------
    for c_lower, c_orig in parent_map.items():
        c_tokens = _normalize_tokens(c_lower)
        sub_names = valid_subs_per_cat.get(c_lower, set())

        # Check subcategories first (higher specificity)
        for s_lower in sub_names:
            s_orig = subcategory_map.get((c_lower, s_lower))
            s_tokens = _normalize_tokens(s_lower)

            # Exact subcategory in subjects -> Highest score (12)
            if s_tokens and s_tokens <= subjects_tokens:
                matches.append((12, c_orig, s_orig))
            elif s_lower in subjects_lower:
                matches.append((11, c_orig, s_orig))
            # Subcategory in title -> High score (9)
            elif s_tokens and s_tokens <= title_tokens:
                matches.append((9, c_orig, s_orig))
            elif s_lower in title_lower:
                matches.append((8, c_orig, s_orig))
            # Subcategory in description -> Moderate score (6)
            elif s_tokens and s_tokens <= full_tokens:
                matches.append((6, c_orig, s_orig))

        # Check parent category
        if c_tokens and c_tokens <= subjects_tokens:
            matches.append((8, c_orig, None))
        elif c_lower in subjects_lower:
            matches.append((7, c_orig, None))
        elif c_tokens and c_tokens <= title_tokens:
            matches.append((6, c_orig, None))
        elif c_tokens and c_tokens <= full_tokens:
            matches.append((4, c_orig, None))

    # -------------------------------------------------------------
    # 2. Taxonomy & Vocabulary Mapping
    # -------------------------------------------------------------
    for keywords, target_cat, target_sub in TAXONOMY_MAP:
        cat_lower = target_cat.lower()
        if cat_lower not in parent_map:
            continue
        c_orig = parent_map[cat_lower]

        s_orig: str | None = None
        if target_sub:
            sub_lower = target_sub.lower()
            if (cat_lower, sub_lower) in subcategory_map:
                s_orig = subcategory_map[(cat_lower, sub_lower)]

        for kw in keywords:
            # Multi-word specific taxonomic phrases (e.g. 'russian literature', 'literary fiction') get highest specificity
            is_specific_phrase = " " in kw or len(kw) > 7
            # Check subject match (Score 14 for specific phrases, 10 otherwise)
            if _match_phrase(kw, subjects_lower, subjects_tokens):
                score = 14 if is_specific_phrase else 10
                matches.append((score, c_orig, s_orig))
                break
            # Check title match (Score 13 for specific titles, 8 otherwise)
            elif _match_phrase(kw, title_lower, title_tokens):
                score = 13 if is_specific_phrase else 8
                matches.append((score, c_orig, s_orig))
                break
            # Check description / full text match (Score 5)
            elif _match_phrase(kw, description_lower, full_tokens):
                matches.append((5, c_orig, s_orig))
                break

    # -------------------------------------------------------------
    # 3. Resolve Best Match with Confidence Threshold
    # -------------------------------------------------------------
    if not matches:
        return None, None

    # Filter out matches where parent is not in categories
    valid_matches: list[tuple[int, str, str | None]] = []
    for score, cat_name, sub_name in matches:
        c_lower = cat_name.lower()
        if c_lower not in parent_map:
            continue
        valid_cat = parent_map[c_lower]

        valid_sub: str | None = None
        if sub_name:
            s_lower = sub_name.lower()
            if (c_lower, s_lower) in subcategory_map:
                valid_sub = subcategory_map[(c_lower, s_lower)]

        valid_matches.append((score, valid_cat, valid_sub))

    if not valid_matches:
        return None, None

    # Sort primarily by score, and secondarily prefer matches having a subcategory
    valid_matches.sort(key=lambda m: (m[0], 1 if m[2] is not None else 0), reverse=True)
    best_score, best_cat, best_sub = valid_matches[0]

    # Minimum confidence threshold: score >= 4
    if best_score < 4:
        return None, None

    return best_cat, best_sub
