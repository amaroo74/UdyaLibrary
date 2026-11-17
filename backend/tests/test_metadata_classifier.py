from app.metadata.classifier import suggest_category


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
    assert suggest_category(
        {
            "title": "Ikigai",
            "author": "Héctor García",
            "publisher": "Penguin",
            "subjects": [],
        },
        [
            {
                "name": "Non-Fiction",
                "subcategories": [{"name": "Self-Help"}],
            }
        ],
    ) == ("Non-Fiction", "Self-Help")


def test_suggest_category_classifies_physics_using_existing_category_names():
    assert suggest_category(
        {"title": "Introduction to Physics", "subjects": []},
        [{"name": "Science", "subcategories": [{"name": "Physics"}]}],
    ) == ("Science", "Physics")
