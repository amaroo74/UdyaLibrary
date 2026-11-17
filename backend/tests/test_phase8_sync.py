import json
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.main import app
from app.models import Book, SyncConflict, SyncQueueItem, UserRole
from app.auth.security import create_access_token
from app.sync.service import get_remote_session_factory, resolve_conflict, sync_two_way

client = TestClient(app)


def get_admin_headers():
    token = create_access_token(
        user_id=1,
        email="admin@udayalibrary.org",
        role=UserRole.ADMINISTRATOR.value,
        name="Library Administrator",
        device_id="admin-device-sync",
    )
    return {"Authorization": f"Bearer {token}", "X-Device-ID": "admin-device-sync"}


def test_local_only_mode_when_no_remote_configured():
    admin_headers = get_admin_headers()
    old_url = os.environ.pop("SYNC_DATABASE_URL", None)
    old_pg = os.environ.pop("POSTGRES_URL", None)

    try:
        stock = f"LCL-{uuid.uuid4().hex[:6]}"
        resp = client.post("/api/books", json={"stock_number": stock, "title": "Local First Guide"}, headers=admin_headers)
        assert resp.status_code == 201
        book_id = resp.json()["id"]

        status_resp = client.get("/api/sync/status", headers=admin_headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["configured"] is False
        assert status_data["mode"] == "local_only"
        assert status_data["pending_changes"] >= 1

        trig_resp = client.post("/api/sync/trigger", json={}, headers=admin_headers)
        assert trig_resp.status_code == 200
        trig_data = trig_resp.json()
        assert trig_data["status"] == "local_only"
        assert "local-only mode" in trig_data["message"].lower()

    finally:
        if old_url:
            os.environ["SYNC_DATABASE_URL"] = old_url
        if old_pg:
            os.environ["POSTGRES_URL"] = old_pg


def test_offline_change_queue_captures_all_crud_operations():
    admin_headers = get_admin_headers()
    stock = f"QOP-{uuid.uuid4().hex[:6]}"

    # 1. CREATE
    resp_create = client.post("/api/books", json={"stock_number": stock, "title": "Queue Test Book"}, headers=admin_headers)
    assert resp_create.status_code == 201
    book_id = resp_create.json()["id"]

    from app.database import SessionLocal
    db: Session = SessionLocal()

    q_create = db.scalars(
        select(SyncQueueItem)
        .where(SyncQueueItem.operation == "CREATE", SyncQueueItem.payload.contains(f'"{stock}"'))
    ).first()
    assert q_create is not None
    assert q_create.status == "PENDING"
    assert q_create.device_id == "admin-device-sync"

    # 2. UPDATE
    resp_update = client.patch(f"/api/books/{book_id}", json={"title": "Queue Test Book Updated"}, headers=admin_headers)
    assert resp_update.status_code == 200

    q_update = db.scalars(
        select(SyncQueueItem)
        .where(SyncQueueItem.operation == "UPDATE", SyncQueueItem.payload.contains(f'"{stock}"'))
    ).first()
    assert q_update is not None
    assert q_update.status == "PENDING"
    assert q_update.device_id == "admin-device-sync"

    # 3. DELETE (Soft delete)
    resp_delete = client.delete(f"/api/books/{book_id}", headers=admin_headers)
    assert resp_delete.status_code == 204

    q_delete = db.scalars(
        select(SyncQueueItem)
        .where(SyncQueueItem.operation == "DELETE", SyncQueueItem.payload.contains(f'"{stock}"'))
    ).first()
    assert q_delete is not None
    assert q_delete.status == "PENDING"
    assert q_delete.device_id == "admin-device-sync"

    # 4. RESTORE
    resp_restore = client.patch(f"/api/books/{book_id}/restore", headers=admin_headers)
    assert resp_restore.status_code == 200

    q_restore = db.scalars(
        select(SyncQueueItem)
        .where(SyncQueueItem.operation == "RESTORE", SyncQueueItem.payload.contains(f'"{stock}"'))
    ).first()
    assert q_restore is not None
    assert q_restore.status == "PENDING"
    assert q_restore.device_id == "admin-device-sync"

    db.close()


def test_sync_push_and_pull_with_remote_cloud_storage(tmp_path):
    admin_headers = get_admin_headers()
    remote_db_file = tmp_path / "remote_cloud.db"
    remote_url = f"sqlite:///{remote_db_file}"

    # Step 1: Create a book locally
    stock_local = f"PUSH-{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/api/books",
        json={"stock_number": stock_local, "title": "Local Novel", "author": "Kerala Writer", "price": 250.0},
        headers=admin_headers,
    )
    assert resp.status_code == 201

    # Step 2: Push sync to remote
    from app.database import SessionLocal
    local_db: Session = SessionLocal()

    sync_result = sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")
    assert sync_result["status"] == "success"
    assert sync_result["pushed"] >= 1

    # Verify book exists in remote storage
    RemoteSession = get_remote_session_factory(remote_url)
    remote_db: Session = RemoteSession()
    remote_book = remote_db.scalar(select(Book).where(Book.stock_number == stock_local))
    assert remote_book is not None
    assert remote_book.title == "Local Novel"
    assert remote_book.author == "Kerala Writer"
    assert float(remote_book.price) == 250.0

    # Step 3: Simulate another device adding a book directly to the remote cloud database
    stock_remote = f"PULL-{uuid.uuid4().hex[:6]}"
    remote_book_2 = Book(
        serial_number=f"UDY-RMT-{uuid.uuid4().hex[:4]}",
        stock_number=stock_remote,
        title="Remote Cloud Poetry",
        author="Poet from Branch B",
        version=1,
        device_id="other-branch-device",
    )
    remote_db.add(remote_book_2)
    remote_db.commit()
    remote_db.close()

    # Step 4: Perform pull sync
    pull_result = sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")
    assert pull_result["status"] == "success"
    assert pull_result["pulled"] >= 1

    # Verify pulled book exists in local SQLite database
    pulled_book = local_db.scalar(select(Book).where(Book.stock_number == stock_remote))
    assert pulled_book is not None
    assert pulled_book.title == "Remote Cloud Poetry"
    assert pulled_book.author == "Poet from Branch B"

    local_db.close()


def test_conflict_detection_never_silently_overwrites(tmp_path):
    admin_headers = get_admin_headers()
    remote_db_file = tmp_path / "remote_conflict.db"
    remote_url = f"sqlite:///{remote_db_file}"

    stock = f"CONF-{uuid.uuid4().hex[:6]}"

    # 1. Register book locally and sync to remote so both start aligned
    resp = client.post("/api/books", json={"stock_number": stock, "title": "Original Title", "price": 100.0}, headers=admin_headers)
    assert resp.status_code == 201
    book_id = resp.json()["id"]

    from app.database import SessionLocal
    local_db: Session = SessionLocal()
    sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")

    # 2. Remote device modifies the book (e.g. at Central Branch)
    RemoteSession = get_remote_session_factory(remote_url)
    remote_db: Session = RemoteSession()
    r_book = remote_db.scalar(select(Book).where(Book.stock_number == stock))
    assert r_book is not None
    r_book.title = "Central Branch Modified Title"
    r_book.version = 5  # Higher version from concurrent remote edit
    r_book.device_id = "central-branch-device"
    remote_db.commit()
    remote_db.close()

    # 3. Local device modifies the same book while offline
    resp_edit = client.patch(f"/api/books/{book_id}", json={"title": "Local Branch Offline Title"}, headers=admin_headers)
    assert resp_edit.status_code == 200

    # 4. Trigger synchronization
    result = sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")

    # Conflict must be detected!
    assert result["conflicts_found"] >= 1

    # Verify conflict record exists
    conflict = local_db.scalar(
        select(SyncConflict)
        .where(SyncConflict.stock_number == stock, SyncConflict.is_resolved.is_(False))
    )
    assert conflict is not None
    assert conflict.conflict_type == "CONCURRENT_UPDATE"

    # Verify neither local nor remote was silently overwritten!
    local_check = local_db.scalar(select(Book).where(Book.stock_number == stock))
    assert local_check.title == "Local Branch Offline Title"

    remote_check_db = RemoteSession()
    remote_check = remote_check_db.scalar(select(Book).where(Book.stock_number == stock))
    assert remote_check.title == "Central Branch Modified Title"
    remote_check_db.close()

    local_db.close()


def test_conflict_detection_stock_number_collision(tmp_path):
    admin_headers = get_admin_headers()
    remote_db_file = tmp_path / "remote_stock_collision.db"
    remote_url = f"sqlite:///{remote_db_file}"

    colliding_stock = f"DUP-{uuid.uuid4().hex[:6]}"

    # Device A (remote) creates book with stock X
    RemoteSession = get_remote_session_factory(remote_url)
    remote_db: Session = RemoteSession()
    remote_db.add(Book(
        serial_number="UDY-REM-001",
        stock_number=colliding_stock,
        title="Remote History Volume",
        author="Historian A",
        version=1,
        device_id="device-branch-remote",
    ))
    remote_db.commit()
    remote_db.close()

    # Device B (local) creates a completely different book with same stock X
    resp = client.post(
        "/api/books",
        json={"stock_number": colliding_stock, "title": "Local Science Volume", "author": "Scientist B"},
        headers=admin_headers,
    )
    assert resp.status_code == 201

    from app.database import SessionLocal
    local_db: Session = SessionLocal()

    sync_result = sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")
    assert sync_result["conflicts_found"] >= 1

    # Conflict record recorded with STOCK_COLLISION
    conflict = local_db.scalar(
        select(SyncConflict).where(SyncConflict.stock_number == colliding_stock)
    )
    assert conflict is not None
    assert conflict.conflict_type == "STOCK_COLLISION"

    local_db.close()


def test_recovery_after_interrupted_synchronization(tmp_path):
    admin_headers = get_admin_headers()
    remote_db_file = tmp_path / "remote_interrupted.db"
    remote_url = f"sqlite:///{remote_db_file}"

    # Register 3 books locally
    s1 = f"INT1-{uuid.uuid4().hex[:4]}"
    s2 = f"INT2-{uuid.uuid4().hex[:4]}"
    s3 = f"INT3-{uuid.uuid4().hex[:4]}"

    client.post("/api/books", json={"stock_number": s1, "title": "Book 1"}, headers=admin_headers)
    client.post("/api/books", json={"stock_number": s2, "title": "Book 2"}, headers=admin_headers)
    client.post("/api/books", json={"stock_number": s3, "title": "Book 3"}, headers=admin_headers)

    from app.database import SessionLocal
    local_db: Session = SessionLocal()

    # Simulate network disconnect after pushing 1 item
    with pytest.raises(ConnectionError):
        sync_two_way(
            local_db,
            remote_url=remote_url,
            device_id="admin-device-sync",
            fail_after_push_count=1,
        )

    # Reconnect and trigger normal synchronization
    recovery_result = sync_two_way(local_db, remote_url=remote_url, device_id="admin-device-sync")
    assert recovery_result["status"] == "success"

    # Verify all 3 books exist on remote
    RemoteSession = get_remote_session_factory(remote_url)
    remote_db: Session = RemoteSession()
    all_remote_stocks = set(remote_db.scalars(select(Book.stock_number)).all())
    assert s1 in all_remote_stocks
    assert s2 in all_remote_stocks
    assert s3 in all_remote_stocks
    remote_db.close()

    local_db.close()


def test_conflict_resolution_api(tmp_path):
    admin_headers = get_admin_headers()
    remote_db_file = tmp_path / "remote_resolve.db"
    remote_url = f"sqlite:///{remote_db_file}"

    from app.database import SessionLocal
    local_db: Session = SessionLocal()

    stock = f"RES-{uuid.uuid4().hex[:6]}"
    conflict_id = str(uuid.uuid4())

    conflict = SyncConflict(
        conflict_id=conflict_id,
        device_id="test-device",
        entity_type="book",
        stock_number=stock,
        conflict_type="STOCK_COLLISION",
        local_data=json.dumps({"stock_number": stock, "title": "Local Resolution Title"}),
        remote_data=json.dumps({"stock_number": stock, "title": "Remote Resolution Title"}),
        is_resolved=False,
    )
    local_db.add(conflict)
    local_db.commit()

    # List conflicts via API
    list_resp = client.get("/api/sync/conflicts", headers=admin_headers)
    assert list_resp.status_code == 200
    conflicts_list = list_resp.json()
    assert any(c["conflict_id"] == conflict_id for c in conflicts_list)

    # Resolve conflict with KEEP_LOCAL
    res_resp = client.post(
        f"/api/sync/conflicts/{conflict_id}/resolve",
        json={"strategy": "KEEP_LOCAL", "remote_url": remote_url},
        headers=admin_headers,
    )
    assert res_resp.status_code == 200
    assert res_resp.json()["status"] == "resolved"

    # Verify marked resolved
    local_db.expire_all()
    resolved_conflict = local_db.scalar(
        select(SyncConflict).where(SyncConflict.conflict_id == conflict_id)
    )
    assert resolved_conflict.is_resolved is True
    assert resolved_conflict.resolution_strategy == "KEEP_LOCAL"

    local_db.close()
