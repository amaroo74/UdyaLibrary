import json
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AuditLog,
    Book,
    Category,
    SyncConflict,
    SyncQueueItem,
    SyncState,
    User,
    UserRole,
    utc_now,
)


@pytest.fixture
def db_session():
    """Create a completely isolated in-memory SQLite database for testing models."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_book_model_creation_and_fields(db_session: Session):
    """Test standard Book record creation and persistent catalogue fields."""
    uid = uuid.uuid4().hex[:6]
    book = Book(
        serial_number=f"UDY-{uid}",
        stock_number=f"STK-{uid}",
        title="ഇന്ദുലേഖ (Indulekha)",
        author="O. Chandu Menon",
        publisher="DC Books",
        category="Fiction",
        subcategory="Novel",
        price=180.00,
        price_source="Google Books",
        price_confirmed=True,
        version=1,
        device_id="desktop-main",
    )
    db_session.add(book)
    db_session.commit()
    db_session.refresh(book)

    assert book.id is not None
    assert book.serial_number == f"UDY-{uid}"
    assert book.stock_number == f"STK-{uid}"
    assert book.title == "ഇന്ദുലേഖ (Indulekha)"
    assert book.author == "O. Chandu Menon"
    assert book.publisher == "DC Books"
    assert book.category == "Fiction"
    assert book.subcategory == "Novel"
    assert float(book.price) == 180.00
    assert book.price_confirmed is True
    assert book.version == 1
    assert book.device_id == "desktop-main"
    assert book.is_deleted is False
    assert book.deleted_at is None
    assert isinstance(book.created_at, datetime)
    assert isinstance(book.updated_at, datetime)


def test_book_unique_stock_number_constraint(db_session: Session):
    """Verify that duplicate stock numbers are rejected by the database."""
    stock = f"STK-DUP-{uuid.uuid4().hex[:6]}"
    b1 = Book(serial_number="UDY-000001", stock_number=stock, title="First Copy")
    db_session.add(b1)
    db_session.commit()

    b2 = Book(serial_number="UDY-000002", stock_number=stock, title="Second Copy")
    db_session.add(b2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_book_unique_serial_number_constraint(db_session: Session):
    """Verify that duplicate serial numbers are rejected by the database."""
    serial = f"UDY-{uuid.uuid4().hex[:6]}"
    b1 = Book(serial_number=serial, stock_number="STK-001", title="First Copy")
    db_session.add(b1)
    db_session.commit()

    b2 = Book(serial_number=serial, stock_number="STK-002", title="Second Copy")
    db_session.add(b2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_repeated_titles_and_authors_allowed(db_session: Session):
    """Verify that multiple physical copies of the same book are permitted with unique stock numbers."""
    b1 = Book(serial_number="UDY-REP-01", stock_number="STK-REP-01", title="Aarachaar", author="K.R. Meera")
    b2 = Book(serial_number="UDY-REP-02", stock_number="STK-REP-02", title="Aarachaar", author="K.R. Meera")
    db_session.add_all([b1, b2])
    db_session.commit()

    copies = db_session.scalars(select(Book).where(Book.title == "Aarachaar")).all()
    assert len(copies) == 2
    assert copies[0].stock_number != copies[1].stock_number


def test_book_soft_delete(db_session: Session):
    """Test soft delete attributes on the Book model."""
    book = Book(serial_number="UDY-DEL-01", stock_number="STK-DEL-01", title="To Be Deleted")
    db_session.add(book)
    db_session.commit()

    # Soft delete
    book.is_deleted = True
    book.deleted_at = utc_now()
    db_session.commit()
    db_session.refresh(book)

    assert book.is_deleted is True
    assert book.deleted_at is not None


def test_category_hierarchy_and_relationships(db_session: Session):
    """Test Category model parent-child relationships and cascade behavior."""
    parent_cat = Category(name="Literature")
    db_session.add(parent_cat)
    db_session.commit()
    db_session.refresh(parent_cat)

    sub1 = Category(name="Poetry", parent_id=parent_cat.id)
    sub2 = Category(name="Drama", parent_id=parent_cat.id)
    db_session.add_all([sub1, sub2])
    db_session.commit()
    db_session.refresh(parent_cat)

    assert len(parent_cat.subcategories) == 2
    sub_names = [s.name for s in parent_cat.subcategories]
    assert "Poetry" in sub_names
    assert "Drama" in sub_names

    # Check child points to parent
    db_session.refresh(sub1)
    assert sub1.parent is not None
    assert sub1.parent.name == "Literature"


def test_user_model_and_roles(db_session: Session):
    """Test User model, roles, and unique email constraints."""
    user = User(
        email="librarian@udayalibrary.org",
        name="Anitha Librarian",
        password_hash="scrypt_hash_example",
        salt="salt_hex_example",
        role=UserRole.LIBRARIAN.value,
        is_active=True,
        trusted_device_id="device-tablet-01",
        trusted_pin_hash="pin_hash_example",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.email == "librarian@udayalibrary.org"
    assert user.role == UserRole.LIBRARIAN.value
    assert user.is_active is True
    assert user.trusted_device_id == "device-tablet-01"

    # Enforce unique email
    duplicate_user = User(
        email="librarian@udayalibrary.org",
        name="Duplicate Librarian",
        password_hash="pw2",
        salt="s2",
        role=UserRole.RESTRICTED_LIBRARIAN.value,
    )
    db_session.add(duplicate_user)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_audit_log_model(db_session: Session):
    """Test AuditLog model logging actions with JSON details and actor metadata."""
    log = AuditLog(
        entity_type="book",
        entity_id=42,
        action="book_price_updated",
        details=json.dumps({"before": 100, "after": 150}),
        actor="admin@udayalibrary.org",
        actor_role="administrator",
        device_id="desktop-admin",
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    assert log.id is not None
    assert log.entity_type == "book"
    assert log.entity_id == 42
    assert log.action == "book_price_updated"
    assert json.loads(log.details) == {"before": 100, "after": 150}
    assert log.actor == "admin@udayalibrary.org"
    assert log.actor_role == "administrator"
    assert log.device_id == "desktop-admin"
    assert isinstance(log.created_at, datetime)


def test_sync_queue_model(db_session: Session):
    """Test SyncQueueItem model capturing offline change operations and status transitions."""
    ch_id = str(uuid.uuid4())
    item = SyncQueueItem(
        change_id=ch_id,
        device_id="laptop-erattapuzha",
        entity_type="book",
        entity_id=10,
        operation="CREATE",
        payload=json.dumps({"stock_number": "STK-999", "title": "Queued Novel"}),
        status="PENDING",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert item.id is not None
    assert item.change_id == ch_id
    assert item.status == "PENDING"
    assert item.operation == "CREATE"
    assert item.synced_at is None

    # Status transition to SYNCED
    item.status = "SYNCED"
    item.synced_at = utc_now()
    db_session.commit()
    db_session.refresh(item)
    assert item.status == "SYNCED"
    assert item.synced_at is not None

    # Change ID uniqueness
    dupe_item = SyncQueueItem(
        change_id=ch_id,
        device_id="laptop-erattapuzha",
        entity_type="book",
        operation="UPDATE",
        payload="{}",
    )
    db_session.add(dupe_item)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sync_conflict_model(db_session: Session):
    """Test SyncConflict model recording detected collisions and resolution metadata."""
    conf_id = str(uuid.uuid4())
    conflict = SyncConflict(
        conflict_id=conf_id,
        device_id="device-branch-b",
        entity_type="book",
        stock_number="STK-CONFLICT-01",
        conflict_type="CONCURRENT_UPDATE",
        local_data=json.dumps({"title": "Local Branch Edit"}),
        remote_data=json.dumps({"title": "Remote Central Edit"}),
        is_resolved=False,
    )
    db_session.add(conflict)
    db_session.commit()
    db_session.refresh(conflict)

    assert conflict.id is not None
    assert conflict.conflict_id == conf_id
    assert conflict.stock_number == "STK-CONFLICT-01"
    assert conflict.conflict_type == "CONCURRENT_UPDATE"
    assert conflict.is_resolved is False
    assert conflict.resolution_strategy is None
    assert conflict.resolved_at is None

    # Resolve conflict
    conflict.is_resolved = True
    conflict.resolution_strategy = "KEEP_LOCAL"
    conflict.resolved_at = utc_now()
    db_session.commit()
    db_session.refresh(conflict)

    assert conflict.is_resolved is True
    assert conflict.resolution_strategy == "KEEP_LOCAL"
    assert conflict.resolved_at is not None


def test_sync_state_model(db_session: Session):
    """Test SyncState model for tracking sync timestamps and cursor state."""
    state = SyncState(key="last_sync_completed_at", value="2026-11-16T10:00:00Z")
    db_session.add(state)
    db_session.commit()
    db_session.refresh(state)

    assert state.id is not None
    assert state.key == "last_sync_completed_at"
    assert state.value == "2026-11-16T10:00:00Z"

    # Update state value
    state.value = "2026-11-16T12:00:00Z"
    db_session.commit()
    db_session.refresh(state)
    assert state.value == "2026-11-16T12:00:00Z"

    # Unique key constraint
    dupe_state = SyncState(key="last_sync_completed_at", value="2026-11-16T14:00:00Z")
    db_session.add(dupe_state)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sync_service_push_pull_and_conflict_resolution(tmp_path):
    """Test two-way synchronization engine directly with database sessions."""
    from app.sync.service import sync_two_way, resolve_conflict, get_sync_status, get_remote_session_factory

    # 1. Setup local and remote database engines
    local_db_path = tmp_path / "local.db"
    remote_db_path = tmp_path / "remote.db"
    local_url = f"sqlite:///{local_db_path}"
    remote_url = f"sqlite:///{remote_db_path}"

    LocalSession = get_remote_session_factory(local_url)
    RemoteSession = get_remote_session_factory(remote_url)

    local_db: Session = LocalSession()
    remote_db: Session = RemoteSession()

    try:
        # 2. Local-only status check before any remote is configured
        status = get_sync_status(local_db, device_id="device-local")
        assert status["pending_changes"] == 0
        assert status["unresolved_conflicts"] == 0

        # 3. Add book locally and enqueue offline CREATE change
        stock = f"STK-SYNC-{uuid.uuid4().hex[:6]}"
        book = Book(
            serial_number=f"UDY-S1",
            stock_number=stock,
            title="Local Offline Novel",
            author="Kerala Author",
            version=1,
            device_id="device-local",
        )
        local_db.add(book)
        local_db.flush()

        queue_item = SyncQueueItem(
            change_id=str(uuid.uuid4()),
            device_id="device-local",
            entity_type="book",
            entity_id=book.id,
            operation="CREATE",
            payload=json.dumps({
                "serial_number": book.serial_number,
                "stock_number": book.stock_number,
                "title": book.title,
                "author": book.author,
                "version": 1,
            }),
            status="PENDING",
        )
        local_db.add(queue_item)
        local_db.commit()

        # 4. Run two-way sync to push local change to remote
        res = sync_two_way(local_db, remote_url=remote_url, device_id="device-local")
        assert res["status"] == "success"
        assert res["pushed"] == 1
        assert res["conflicts_found"] == 0

        # Verify remote received book
        r_book = remote_db.scalar(select(Book).where(Book.stock_number == stock))
        assert r_book is not None
        assert r_book.title == "Local Offline Novel"

        # 5. Remote device adds a book, local pulls it
        remote_stock = f"STK-RMT-{uuid.uuid4().hex[:6]}"
        remote_db.add(Book(
            serial_number="UDY-R2",
            stock_number=remote_stock,
            title="Remote Branch Poetry",
            version=1,
            device_id="other-branch",
        ))
        remote_db.commit()

        pull_res = sync_two_way(local_db, remote_url=remote_url, device_id="device-local")
        assert pull_res["status"] == "success"
        assert pull_res["pulled"] == 1

        pulled_local = local_db.scalar(select(Book).where(Book.stock_number == remote_stock))
        assert pulled_local is not None
        assert pulled_local.title == "Remote Branch Poetry"

        # 6. Test conflict detection: Remote edits title, local concurrently edits title
        r_book.title = "Remote Conflicting Title"
        r_book.version = 3
        remote_db.commit()

        book.title = "Local Conflicting Title"
        book.version = 2
        local_db.add(SyncQueueItem(
            change_id=str(uuid.uuid4()),
            device_id="device-local",
            entity_type="book",
            entity_id=book.id,
            operation="UPDATE",
            payload=json.dumps({"stock_number": stock, "title": "Local Conflicting Title", "version": 2}),
            status="PENDING",
        ))
        local_db.commit()

        conf_res = sync_two_way(local_db, remote_url=remote_url, device_id="device-local")
        assert conf_res["conflicts_found"] >= 1

        # Check conflict record exists
        conflict = local_db.scalar(select(SyncConflict).where(SyncConflict.stock_number == stock))
        assert conflict is not None
        assert conflict.conflict_type == "CONCURRENT_UPDATE"
        assert conflict.is_resolved is False

        # Verify safe conflict resolution with KEEP_LOCAL
        resolve_res = resolve_conflict(
            local_db,
            conflict_id=conflict.conflict_id,
            strategy="KEEP_LOCAL",
            remote_url=remote_url,
        )
        assert resolve_res["status"] == "resolved"

        local_db.refresh(conflict)
        assert conflict.is_resolved is True
        assert conflict.resolution_strategy == "KEEP_LOCAL"

    finally:
        local_db.close()
        remote_db.close()

