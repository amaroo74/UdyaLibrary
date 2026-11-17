from datetime import timedelta
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.security import create_access_token
from app.database import SessionLocal
from app.main import app
from app.models import SyncQueueItem, UserRole


client = TestClient(app)


def token_headers(
    user_id: int = 1,
    email: str = "admin@udayalibrary.org",
    role: str = UserRole.ADMINISTRATOR.value,
    device_id: str = "auth-test-device",
    expires_delta: timedelta | None = None,
) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        email=email,
        role=role,
        name="Authentication Test User",
        device_id=device_id,
        expires_delta=expires_delta,
    )
    return {"Authorization": f"Bearer {token}"}


def test_catalogue_endpoints_reject_missing_and_invalid_authentication():
    endpoints = [
        ("get", "/api/books"),
        ("get", "/api/books/deleted"),
        ("get", "/api/books/meta/categories"),
        ("get", "/api/categories"),
        ("get", "/api/bulk/export/csv"),
        ("get", "/api/bulk/export/xlsx"),
        ("get", "/api/bulk/export/pdf"),
        ("get", "/api/recognition/lookup?title=test"),
        ("get", "/api/sync/status"),
        ("get", "/api/auth/audit-logs"),
    ]

    for method, path in endpoints:
        request = getattr(client, method)
        assert request(path).status_code == 401
        assert request(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_catalogue_mutations_reject_missing_authentication():
    book_payload = {"stock_number": f"AUTH-{uuid.uuid4().hex[:8]}", "title": "Auth Test"}
    requests = [
        ("post", "/api/books", {"json": book_payload}),
        ("post", "/api/categories", {"json": {"name": f"Auth-{uuid.uuid4().hex[:8]}"}}),
        ("post", "/api/bulk/batch-register", {"json": [book_payload]}),
        (
            "post",
            "/api/bulk/import",
            {"files": {"file": ("catalogue.csv", b"Stock Number,Book Title\nX,Test", "text/csv")}},
        ),
        (
            "post",
            "/api/recognition/scan",
            {"files": {"file": ("cover.png", b"not-an-image", "image/png")}},
        ),
        ("post", "/api/sync/trigger", {"json": {}}),
        (
            "post",
            "/api/bulk/backup/restore",
            {"files": {"file": ("backup.db", b"not-a-database", "application/octet-stream")}},
        ),
    ]

    for method, path, kwargs in requests:
        assert getattr(client, method)(path, **kwargs).status_code == 401


def test_expired_authentication_is_rejected():
    expired_headers = token_headers(expires_delta=timedelta(minutes=-1))
    response = client.get("/api/books", headers=expired_headers)
    assert response.status_code == 401


def test_authenticated_administrator_can_use_catalogue_operations():
    headers = token_headers()
    stock = f"AUTH-ADMIN-{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/api/books",
        headers=headers,
        json={"stock_number": stock, "title": "Authenticated Admin Book"},
    )
    assert created.status_code == 201
    book_id = created.json()["id"]

    assert client.get("/api/books", headers=headers).status_code == 200
    assert client.get("/api/bulk/export/csv", headers=headers).status_code == 200
    assert client.get("/api/sync/status", headers=headers).status_code == 200
    assert client.post("/api/sync/trigger", headers=headers, json={}).status_code == 200

    deleted = client.delete(f"/api/books/{book_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.patch(f"/api/books/{book_id}/restore", headers=headers).status_code == 200
    assert client.delete(f"/api/books/{book_id}", headers=headers).status_code == 204


def test_device_id_propagates_to_batch_and_import_queue_items():
    headers = token_headers(device_id="batch-import-device")
    batch_stock = f"AUTH-BATCH-{uuid.uuid4().hex[:8]}"
    batch_response = client.post(
        "/api/bulk/batch-register",
        headers=headers,
        json=[{"stock_number": batch_stock, "title": "Batch Device Test"}],
    )
    assert batch_response.status_code == 200

    import_stock = f"AUTH-IMPORT-{uuid.uuid4().hex[:8]}"
    import_response = client.post(
        "/api/bulk/import",
        headers=headers,
        files={
            "file": (
                "catalogue.csv",
                f"Stock Number,Book Title\n{import_stock},Import Device Test".encode(),
                "text/csv",
            )
        },
    )
    assert import_response.status_code == 200

    with SessionLocal() as db:
        queue_items = db.scalars(
            select(SyncQueueItem).where(
                SyncQueueItem.device_id == "batch-import-device",
                SyncQueueItem.payload.contains(batch_stock),
            )
        ).all()
        assert queue_items
        import_queue_items = db.scalars(
            select(SyncQueueItem).where(
                SyncQueueItem.device_id == "batch-import-device",
                SyncQueueItem.payload.contains(import_stock),
            )
        ).all()
        assert import_queue_items


def test_restricted_librarian_is_denied_administrative_operations():
    admin_headers = token_headers()
    email = f"restricted_auth_{uuid.uuid4().hex[:8]}@example.test"
    created_user = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "email": email,
            "name": "Restricted Auth Test",
            "password": "RestrictedPassword123!",
            "role": UserRole.RESTRICTED_LIBRARIAN.value,
        },
    )
    assert created_user.status_code == 201
    restricted_login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "RestrictedPassword123!",
            "device_id": "restricted-auth-device",
        },
    )
    assert restricted_login.status_code == 200
    restricted_headers = {"Authorization": f"Bearer {restricted_login.json()['access_token']}"}

    assert client.post(
        "/api/categories",
        headers=restricted_headers,
        json={"name": f"Restricted-{uuid.uuid4().hex[:8]}"},
    ).status_code == 403
    assert client.post("/api/sync/trigger", headers=restricted_headers, json={}).status_code == 403
    assert client.get("/api/auth/audit-logs", headers=restricted_headers).status_code == 403
    assert client.get("/api/bulk/backup/download", headers=restricted_headers).status_code == 403

    book = client.post(
        "/api/books",
        headers=restricted_headers,
        json={
            "stock_number": f"AUTH-RESTRICTED-{uuid.uuid4().hex[:8]}",
            "title": "Restricted Book",
        },
    )
    assert book.status_code == 201
    book_id = book.json()["id"]
    assert client.patch(
        f"/api/books/{book_id}",
        headers=restricted_headers,
        json={"title": "Restricted Book Updated"},
    ).status_code == 200
    assert client.delete(f"/api/books/{book_id}", headers=restricted_headers).status_code == 403
