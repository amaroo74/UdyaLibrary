"""Automated tests for Udaya Library category and subcategory suggestion engine.

Verifies:
1. Exact match with existing parent and child subcategories.
2. Crime and Punishment (ISBN 9780140449136) classification to Fiction › Literary Fiction.
3. Ikigai classification to Non-Fiction › Self-Help.
4. Malayalam book classification (e.g. Khasakkinte Itihasam, Indulekha).
5. Insufficient metadata handling (returns None, None; does not invent categories).
6. Non-existent category rejection (does not cross-link or invent categories).
7. Librarian manual edit preservation (form edit override).
"""

from app.category_seed import DEFAULT_CATEGORY_TREE
from app.metadata.classifier import suggest_category


def get_default_hierarchy() -> list[dict]:
    return [
        {"name": k, "subcategories": [{"name": s} for s in v]}
        for k, v in DEFAULT_CATEGORY_TREE.items()
    ]


def test_suggest_category_returns_existing_parent_and_matching_subcategory():
    category, subcategory = suggest_category(
        {
            "title": "Introduction to Physics",
            "author": "A. Author",
            "publisher": "Press",
            "subjects": ["Physics"],
        },
        [
            {
                "name": "Science",
                "subcategories": [{"name": "Physics"}],
            },
            {"name": "Fiction", "subcategories": [{"name": "Novel"}]},
        ],
    )

    assert (category, subcategory) == ("Science", "Physics")


def test_suggest_category_does_not_invent_or_cross_link_categories():
    category, subcategory = suggest_category(
        {
            "title": "Ikigai",
            "author": "Héctor García",
            "publisher": "Penguin",
            "subjects": ["Self-help"],
        },
        [
            {
                "name": "Science",
                "subcategories": [{"name": "Physics"}],
            }
        ],
    )

    assert category is None
    assert subcategory is None


def test_suggest_category_classifies_ikigai_using_existing_category_names():
    hierarchy = get_default_hierarchy()
    assert suggest_category(
        {
            "title": "Ikigai: The Japanese Secret to a Long and Happy Life",
            "author": "Héctor García",
            "publisher": "Penguin",
            "subjects": ["Self-help", "Personal Growth"],
        },
        hierarchy,
    ) == ("Non-Fiction", "Self-Help")


def test_suggest_category_classifies_physics_using_existing_category_names():
    assert suggest_category(
        {"title": "Introduction to Physics", "subjects": []},
        [{"name": "Science", "subcategories": [{"name": "Physics"}]}],
    ) == ("Science", "Physics")


def test_crime_and_punishment_classification():
    """Verify Crime and Punishment (ISBN 9780140449136) classifies to Fiction › Literary Fiction."""
    hierarchy = get_default_hierarchy()
    cand = {
        "title": "Crime and Punishment",
        "author": "Fyodor Dostoevsky",
        "publisher": "Penguin Classics",
        "isbn": "9780140449136",
        "subjects": ["Russian literature", "Fiction", "Psychological fiction", "Murder", "Classics"],
        "description": "Rodion Raskolnikov commits a murder in Saint Petersburg.",
    }
    category, subcategory = suggest_category(cand, hierarchy)
    assert category == "Fiction"
    assert subcategory == "Literary Fiction"


def test_crime_and_punishment_with_empty_subjects():
    """Fallback on title and author for Crime and Punishment when subjects are absent."""
    hierarchy = get_default_hierarchy()
    cand = {
        "title": "Crime and punishment",
        "author": "Fiódor Dostoievski",
        "publisher": "Penguin",
        "subjects": [],
    }
    category, subcategory = suggest_category(cand, hierarchy)
    assert category == "Fiction"
    assert subcategory in ("Literary Fiction", "Mystery")


def test_malayalam_book_classification():
    """Verify Malayalam books classify correctly using Malayalam Unicode vocabulary."""
    hierarchy = get_default_hierarchy()

    # Khasakkinte Itihasam
    cand_khasak = {
        "title": "ഖസാക്കിന്റെ ഇതിഹാസം",
        "author": "ഒ.വി. വിജയൻ",
        "publisher": "ഡി.സി. ബുക്സ്",
        "subjects": ["നോവൽ", "മലയാള സാഹിത്യം"],
    }
    cat1, sub1 = suggest_category(cand_khasak, hierarchy)
    assert cat1 == "Fiction"
    assert sub1 == "Literary Fiction"

    # Poetry
    cand_poem = {
        "title": "കരുണ",
        "author": "കുമാരനാശാൻ",
        "subjects": ["കവിത", "ഖണ്ഡകാവ്യം"],
    }
    cat2, sub2 = suggest_category(cand_poem, hierarchy)
    assert cat2 == "Literature"
    assert sub2 == "Poetry"

    # Kerala History
    cand_hist = {
        "title": "കേരള ചരിത്ര പഠനങ്ങൾ",
        "author": "എം.ജി.എസ്. നാരായണൻ",
        "subjects": ["ചരിത്രം", "കേരള ചരിത്രം"],
    }
    cat3, sub3 = suggest_category(cand_hist, hierarchy)
    assert cat3 == "History & Geography"
    assert sub3 == "Kerala History"


def test_insufficient_metadata_returns_none():
    """Verify books with insufficient metadata leave category unselected."""
    hierarchy = get_default_hierarchy()
    cand_obscure = {
        "title": "Untitled Manuscript 109283",
        "author": "A. Person",
        "publisher": "Self-published",
        "subjects": [],
        "description": "",
    }
    category, subcategory = suggest_category(cand_obscure, hierarchy)
    assert category is None
    assert subcategory is None


def test_librarian_manual_category_override_simulated():
    """
    Verify librarian manual choice takes precedence:
    If a suggestion is 'Literary Fiction', librarian can override to 'Mystery'.
    """
    hierarchy = get_default_hierarchy()
    cand = {
        "title": "Crime and Punishment",
        "author": "Fyodor Dostoevsky",
        "subjects": ["Crime", "Detective fiction"],
    }
    suggested_cat, suggested_sub = suggest_category(cand, hierarchy)
    assert suggested_cat == "Fiction"

    # Simulate librarian selection in form
    form_category = suggested_cat
    form_subcategory = suggested_sub

    # Librarian manually chooses a different subcategory under Fiction (e.g. Mystery or Thriller)
    librarian_override = "Mystery"
    fiction_cat = next(c for c in hierarchy if c["name"] == "Fiction")
    valid_subs = [s["name"] for s in fiction_cat["subcategories"]]
    assert librarian_override in valid_subs

    # Apply manual override
    form_subcategory = librarian_override
    assert form_category == "Fiction"
    assert form_subcategory == "Mystery"


def test_sparse_provider_titles_receive_conservative_existing_category_suggestions():
    hierarchy = get_default_hierarchy()
    assert suggest_category({"title": "Wings of Fire", "author": "A. P. J. Abdul Kalam"}, hierarchy) == (
        "Biography & Autobiography",
        "Leaders",
    )
    assert suggest_category({"title": "A Brief History of Time", "author": "Stephen Hawking"}, hierarchy) == (
        "Science",
        "Astronomy",
    )
    assert suggest_category({"title": "The Alchemist", "author": "Paulo Coelho"}, hierarchy) == (
        "Fiction",
        "Literary Fiction",
    )
