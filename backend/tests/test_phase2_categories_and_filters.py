import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth.security import create_access_token
from app.models import UserRole

client = TestClient(
    app,
    headers={
        "Authorization": "Bearer " + create_access_token(
            user_id=1,
            email="admin@udayalibrary.org",
            role=UserRole.ADMINISTRATOR.value,
            name="Test Administrator",
            device_id="test-admin-device",
        )
    },
)


def test_category_crud_and_hierarchy():
    uid = uuid4_prefix = uuid.uuid4().hex[:6]
    cat_name = f"Science_{uid}"
    sub_name = f"Physics_{uid}"

    # 1. Create top-level category
    res = client.post("/api/categories", json={"name": cat_name})
    assert res.status_code == 201
    cat_science = res.json()
    assert cat_science["name"] == cat_name
    assert cat_science["parent_id"] is None

    # 2. Duplicate top-level category rejected with 409
    res_dupe = client.post("/api/categories", json={"name": cat_name})
    assert res_dupe.status_code == 409

    # 3. Create subcategory under Science
    res_sub = client.post(
        "/api/categories",
        json={"name": sub_name, "parent_id": cat_science["id"]},
    )
    assert res_sub.status_code == 201
    sub_physics = res_sub.json()
    assert sub_physics["name"] == sub_name
    assert sub_physics["parent_id"] == cat_science["id"]

    # 4. Deep nesting beyond subcategory rejected with 400
    res_deep = client.post(
        "/api/categories",
        json={"name": f"Quantum_{uid}", "parent_id": sub_physics["id"]},
    )
    assert res_deep.status_code == 400

    # 5. List categories hierarchy
    res_list = client.get("/api/categories")
    assert res_list.status_code == 200
    tree = res_list.json()
    science_in_tree = next((c for c in tree if c["id"] == cat_science["id"]), None)
    assert science_in_tree is not None
    assert any(s["name"] == sub_name for s in science_in_tree["subcategories"])

    # 6. Delete subcategory
    res_del_sub = client.delete(f"/api/categories/{sub_physics['id']}")
    assert res_del_sub.status_code == 204

    # 7. Delete top-level category
    res_del_cat = client.delete(f"/api/categories/{cat_science['id']}")
    assert res_del_cat.status_code == 204


def test_advanced_sorting_and_price_filters():
    uid = uuid.uuid4().hex[:6]
    st_prefix = f"FLT-{uid}"

    # Setup 3 books with distinct titles and prices
    b1_res = client.post(
        "/api/books",
        json={
            "stock_number": f"{st_prefix}-A",
            "title": f"Alpha Astronomy {uid}",
            "author": "Carl Sagan",
            "price": 450.00,
            "category": f"Astronomy_{uid}",
            "subcategory": f"Cosmology_{uid}",
        },
    )
    assert b1_res.status_code == 201
    b1 = b1_res.json()

    b2_res = client.post(
        "/api/books",
        json={
            "stock_number": f"{st_prefix}-B",
            "title": f"Beta Biology {uid}",
            "author": "Charles Darwin",
            "price": 200.00,
            "category": f"Biology_{uid}",
            "subcategory": f"Evolution_{uid}",
        },
    )
    assert b2_res.status_code == 201
    b2 = b2_res.json()

    b3_res = client.post(
        "/api/books",
        json={
            "stock_number": f"{st_prefix}-C",
            "title": f"Gamma Geology {uid}",
            "author": "Charles Lyell",
            "price": 800.00,
            "category": f"Geology_{uid}",
        },
    )
    assert b3_res.status_code == 201
    b3 = b3_res.json()

    # 1. Sort by title ASC
    res_title_asc = client.get(f"/api/books?q={st_prefix}&sort_by=title&sort_order=asc")
    assert res_title_asc.status_code == 200
    titles = [b["title"] for b in res_title_asc.json()["items"]]
    assert titles == sorted(titles)

    # 2. Sort by price DESC
    res_price_desc = client.get(f"/api/books?q={st_prefix}&sort_by=price&sort_order=desc")
    assert res_price_desc.status_code == 200
    prices = [float(b["price"]) for b in res_price_desc.json()["items"]]
    assert prices == sorted(prices, reverse=True)

    # 3. Price range filter: min 300, max 600
    res_range = client.get(f"/api/books?q={st_prefix}&min_price=300&max_price=600")
    assert res_range.status_code == 200
    items_range = res_range.json()["items"]
    assert len(items_range) == 1
    assert items_range[0]["title"] == b1["title"]

    # 4. Category filter
    res_cat = client.get(f"/api/books?category=Biology_{uid}")
    assert res_cat.status_code == 200
    for b in res_cat.json()["items"]:
        assert b["category"] == f"Biology_{uid}"

    # 5. Clean up created books
    for b in [b1, b2, b3]:
        client.delete(f"/api/books/{b['id']}")


def test_recycle_bin_and_restore():
    uid = uuid.uuid4().hex[:6]
    stock_num = f"RST-{uid}"

    # 1. Create a book
    res_create = client.post(
        "/api/books",
        json={
            "stock_number": stock_num,
            "title": f"Book for Recycle Bin {uid}",
            "author": "Author One",
        },
    )
    assert res_create.status_code == 201
    book = res_create.json()

    # 2. Soft-delete the book
    del_res = client.delete(f"/api/books/{book['id']}")
    assert del_res.status_code == 204

    # 3. Ensure it is NOT in active books list
    active_res = client.get(f"/api/books?q={stock_num}")
    assert active_res.json()["total"] == 0

    # 4. Check that it appears in deleted books
    deleted_res = client.get("/api/books/deleted")
    assert deleted_res.status_code == 200
    deleted_ids = [b["id"] for b in deleted_res.json()["items"]]
    assert book["id"] in deleted_ids

    # 5. Restore the book
    restore_res = client.patch(f"/api/books/{book['id']}/restore")
    assert restore_res.status_code == 200
    assert restore_res.json()["is_deleted"] is False

    # 6. Verify it is now back in active books
    active_after = client.get(f"/api/books?q={stock_num}")
    assert active_after.json()["total"] == 1
    assert active_after.json()["items"][0]["id"] == book["id"]

    # Final cleanup
    client.delete(f"/api/books/{book['id']}")

