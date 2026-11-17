import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from ..database import Base
from ..models import Book, SyncConflict, SyncQueueItem, SyncState, utc_now
from ..services import book_to_dict


def get_sync_database_url() -> str | None:
    """Retrieve remote PostgreSQL/cloud database connection URL from environment."""
    url = os.getenv("SYNC_DATABASE_URL") or os.getenv("POSTGRES_URL")
    if url and url.strip():
        return url.strip()
    return None


def get_remote_session_factory(remote_url: str):
    """Create an engine and sessionmaker for remote cloud database."""
    connect_args = {}
    if remote_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(remote_url, connect_args=connect_args)
    # Ensure remote tables exist
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_sync_status(db: Session, device_id: str = "device-local") -> dict[str, Any]:
    """Retrieve current synchronization status and queue metrics."""
    remote_url = get_sync_database_url()
    pending_count = db.scalar(
        select(SyncQueueItem)
        .where(SyncQueueItem.status == "PENDING")
    )
    # Count of pending items
    pending_count = len(db.scalars(
        select(SyncQueueItem).where(SyncQueueItem.status == "PENDING")
    ).all())

    unresolved_conflicts = len(db.scalars(
        select(SyncConflict).where(SyncConflict.is_resolved.is_(False))
    ).all())

    last_sync_record = db.scalar(
        select(SyncState).where(SyncState.key == "last_sync_completed_at")
    )
    last_synced_at = last_sync_record.value if last_sync_record else None

    return {
        "configured": bool(remote_url),
        "mode": "cloud_sync" if remote_url else "local_only",
        "device_id": device_id,
        "pending_changes": pending_count,
        "unresolved_conflicts": unresolved_conflicts,
        "last_synced_at": last_synced_at,
    }


def sync_two_way(
    db: Session,
    remote_url: str | None = None,
    device_id: str = "device-local",
    fail_after_push_count: int | None = None,  # For testing interrupted sync recovery
) -> dict[str, Any]:
    """
    Perform two-way synchronization between local SQLite and remote PostgreSQL database:
    1. Push local pending outbox changes to remote (idempotent, conflict-aware).
    2. Pull remote changes to local SQLite (conflict-aware, never silently overwriting).
    3. Handles simulated interruption & graceful recovery.
    """
    target_url = remote_url or get_sync_database_url()
    if not target_url:
        return {
            "status": "local_only",
            "message": "Cloud sync is not configured. Running safely in local-only mode.",
            "pushed": 0,
            "pulled": 0,
            "conflicts_found": 0,
            "pending_remaining": len(db.scalars(
                select(SyncQueueItem).where(SyncQueueItem.status == "PENDING")
            ).all()),
        }

    RemoteSession = get_remote_session_factory(target_url)
    remote_db: Session = RemoteSession()

    pushed_count = 0
    pulled_count = 0
    conflicts_found = 0

    try:
        # -------------------------------------------------------------
        # 1. PUSH PHASE: Send local outbox to remote
        # -------------------------------------------------------------
        pending_items = db.scalars(
            select(SyncQueueItem)
            .where(SyncQueueItem.status == "PENDING")
            .order_by(SyncQueueItem.id.asc())
        ).all()

        for idx, item in enumerate(pending_items):
            # Test hook: simulate network interruption midway through push
            if fail_after_push_count is not None and idx >= fail_after_push_count:
                remote_db.commit()
                db.commit()
                raise ConnectionError("Simulated network interruption during synchronization push.")

            try:
                payload = json.loads(item.payload)
            except Exception:
                payload = {}

            stock_no = payload.get("stock_number")
            if not stock_no and item.entity_type == "book":
                item.status = "FAILED"
                item.error_message = "Missing stock number in sync payload"
                continue

            # Query remote book by stock_number
            remote_book = remote_db.scalar(
                select(Book).where(Book.stock_number == stock_no)
            )

            if item.operation == "CREATE":
                if not remote_book:
                    # Clean insert to remote
                    new_remote = Book(
                        serial_number=payload.get("serial_number") or f"REM-{uuid.uuid4().hex[:8]}",
                        stock_number=stock_no,
                        title=payload.get("title", "Untitled"),
                        author=payload.get("author"),
                        publisher=payload.get("publisher"),
                        category=payload.get("category"),
                        subcategory=payload.get("subcategory"),
                        price=payload.get("price"),
                        price_source=payload.get("price_source"),
                        price_confirmed=payload.get("price_confirmed", False),
                        version=payload.get("version", 1),
                        device_id=item.device_id,
                        is_deleted=payload.get("is_deleted", False),
                    )
                    remote_db.add(new_remote)
                    remote_db.flush()
                    item.status = "SYNCED"
                    item.synced_at = utc_now()
                    pushed_count += 1
                else:
                    # Remote already exists with this stock number!
                    # Check if contents match (idempotent repeat)
                    if (
                        remote_book.title == payload.get("title")
                        and remote_book.author == payload.get("author")
                        and remote_book.publisher == payload.get("publisher")
                    ):
                        item.status = "SYNCED"
                        item.synced_at = utc_now()
                        pushed_count += 1
                    else:
                        # Conflict! Stock number collision or concurrent creation
                        conflict = SyncConflict(
                            conflict_id=str(uuid.uuid4()),
                            device_id=item.device_id,
                            entity_type="book",
                            stock_number=stock_no,
                            conflict_type="STOCK_COLLISION",
                            local_data=item.payload,
                            remote_data=json.dumps(book_to_dict(remote_book), ensure_ascii=False, default=str),
                            is_resolved=False,
                        )
                        db.add(conflict)
                        item.status = "CONFLICT"
                        conflicts_found += 1

            elif item.operation == "UPDATE":
                if not remote_book:
                    # Remote book missing
                    conflict = SyncConflict(
                        conflict_id=str(uuid.uuid4()),
                        device_id=item.device_id,
                        entity_type="book",
                        stock_number=stock_no,
                        conflict_type="REMOTE_MISSING",
                        local_data=item.payload,
                        remote_data="{}",
                        is_resolved=False,
                    )
                    db.add(conflict)
                    item.status = "CONFLICT"
                    conflicts_found += 1
                else:
                    local_version = payload.get("version", 1)
                    # Check version concurrency
                    if remote_book.version < local_version or (remote_book.version == local_version and remote_book.device_id == item.device_id):
                        # Safe to apply local updates to remote
                        remote_book.title = payload.get("title", remote_book.title)
                        remote_book.author = payload.get("author", remote_book.author)
                        remote_book.publisher = payload.get("publisher", remote_book.publisher)
                        remote_book.category = payload.get("category", remote_book.category)
                        remote_book.subcategory = payload.get("subcategory", remote_book.subcategory)
                        remote_book.price = payload.get("price", remote_book.price)
                        remote_book.price_source = payload.get("price_source", remote_book.price_source)
                        remote_book.price_confirmed = payload.get("price_confirmed", remote_book.price_confirmed)
                        remote_book.version = local_version
                        remote_book.device_id = item.device_id
                        remote_db.flush()
                        item.status = "SYNCED"
                        item.synced_at = utc_now()
                        pushed_count += 1
                    else:
                        # Remote was edited concurrently by another device!
                        conflict = SyncConflict(
                            conflict_id=str(uuid.uuid4()),
                            device_id=item.device_id,
                            entity_type="book",
                            stock_number=stock_no,
                            conflict_type="CONCURRENT_UPDATE",
                            local_data=item.payload,
                            remote_data=json.dumps(book_to_dict(remote_book), ensure_ascii=False, default=str),
                            is_resolved=False,
                        )
                        db.add(conflict)
                        item.status = "CONFLICT"
                        conflicts_found += 1

            elif item.operation == "DELETE":
                if remote_book:
                    remote_book.is_deleted = True
                    remote_book.deleted_at = utc_now()
                    remote_book.version = (remote_book.version or 1) + 1
                    remote_book.device_id = item.device_id
                    remote_db.flush()
                item.status = "SYNCED"
                item.synced_at = utc_now()
                pushed_count += 1

            elif item.operation == "RESTORE":
                if remote_book:
                    remote_book.is_deleted = False
                    remote_book.deleted_at = None
                    remote_book.version = (remote_book.version or 1) + 1
                    remote_book.device_id = item.device_id
                    remote_db.flush()
                item.status = "SYNCED"
                item.synced_at = utc_now()
                pushed_count += 1

        remote_db.commit()
        db.commit()

        # -------------------------------------------------------------
        # 2. PULL PHASE: Retrieve changes from remote to local
        # -------------------------------------------------------------
        # Get remote books that were created/modified by other devices
        remote_books = remote_db.scalars(
            select(Book).where(Book.device_id != device_id)
        ).all()

        for r_book in remote_books:
            local_book = db.scalar(
                select(Book).where(Book.stock_number == r_book.stock_number)
            )

            # Check if there is an unsynced local pending item for this book
            has_pending = db.scalar(
                select(SyncQueueItem)
                .where(
                    SyncQueueItem.status.in_(("PENDING", "CONFLICT")),
                    SyncQueueItem.payload.contains(f'"{r_book.stock_number}"')
                )
            )

            if not local_book:
                # Book exists on remote but not locally
                if not r_book.is_deleted:
                    new_local = Book(
                        serial_number=r_book.serial_number,
                        stock_number=r_book.stock_number,
                        title=r_book.title,
                        author=r_book.author,
                        publisher=r_book.publisher,
                        category=r_book.category,
                        subcategory=r_book.subcategory,
                        price=r_book.price,
                        price_source=r_book.price_source,
                        price_confirmed=r_book.price_confirmed,
                        version=r_book.version,
                        device_id=r_book.device_id,
                        is_deleted=r_book.is_deleted,
                    )
                    db.add(new_local)
                    pulled_count += 1
            else:
                # Book exists locally
                if has_pending:
                    # Both modified since last sync -> CONFLICT!
                    # Do not overwrite local!
                    conflict = SyncConflict(
                        conflict_id=str(uuid.uuid4()),
                        device_id=device_id,
                        entity_type="book",
                        stock_number=r_book.stock_number,
                        conflict_type="CONCURRENT_UPDATE",
                        local_data=json.dumps(book_to_dict(local_book), ensure_ascii=False, default=str),
                        remote_data=json.dumps(book_to_dict(r_book), ensure_ascii=False, default=str),
                        is_resolved=False,
                    )
                    db.add(conflict)
                    conflicts_found += 1
                else:
                    # Clean remote update: apply to local
                    if r_book.version > local_book.version:
                        local_book.title = r_book.title
                        local_book.author = r_book.author
                        local_book.publisher = r_book.publisher
                        local_book.category = r_book.category
                        local_book.subcategory = r_book.subcategory
                        local_book.price = r_book.price
                        local_book.price_source = r_book.price_source
                        local_book.price_confirmed = r_book.price_confirmed
                        local_book.is_deleted = r_book.is_deleted
                        local_book.deleted_at = r_book.deleted_at
                        local_book.version = r_book.version
                        local_book.device_id = r_book.device_id
                        pulled_count += 1

        # Record last sync timestamp
        now_iso = datetime.now(timezone.utc).isoformat()
        last_sync_state = db.scalar(
            select(SyncState).where(SyncState.key == "last_sync_completed_at")
        )
        if not last_sync_state:
            db.add(SyncState(key="last_sync_completed_at", value=now_iso))
        else:
            last_sync_state.value = now_iso

        db.commit()

        return {
            "status": "success",
            "pushed": pushed_count,
            "pulled": pulled_count,
            "conflicts_found": conflicts_found,
            "pending_remaining": len(db.scalars(
                select(SyncQueueItem).where(SyncQueueItem.status == "PENDING")
            ).all()),
        }

    except Exception as e:
        remote_db.rollback()
        db.rollback()
        raise e
    finally:
        remote_db.close()


def resolve_conflict(
    db: Session,
    conflict_id: str,
    strategy: str,
    resolution_data: dict[str, Any] | None = None,
    remote_url: str | None = None,
) -> dict[str, Any]:
    """
    Safely resolve a sync conflict:
    - KEEP_LOCAL: Keep local record, push local record to remote.
    - KEEP_REMOTE: Replace local record with remote record.
    - RENAME_STOCK: Change local record's stock number so both copies coexist without collision.
    - MANUAL: Apply user-specified fields to both local and remote.
    """
    conflict = db.scalar(
        select(SyncConflict).where(SyncConflict.conflict_id == conflict_id)
    )
    if not conflict:
        raise ValueError("Conflict record not found.")

    local_book = db.scalar(
        select(Book).where(Book.stock_number == conflict.stock_number)
    )
    remote_data = json.loads(conflict.remote_data or "{}")
    local_data = json.loads(conflict.local_data or "{}")
    target_url = remote_url or get_sync_database_url()

    RemoteSession = get_remote_session_factory(target_url) if target_url else None
    remote_db = RemoteSession() if RemoteSession else None

    try:
        if strategy == "KEEP_LOCAL":
            if remote_db and local_book:
                remote_book = remote_db.scalar(
                    select(Book).where(Book.stock_number == conflict.stock_number)
                )
                if remote_book:
                    remote_book.title = local_book.title
                    remote_book.author = local_book.author
                    remote_book.publisher = local_book.publisher
                    remote_book.category = local_book.category
                    remote_book.subcategory = local_book.subcategory
                    remote_book.price = local_book.price
                    remote_book.version = (local_book.version or 1) + 1
                    remote_db.commit()

        elif strategy == "KEEP_REMOTE":
            if local_book and remote_data:
                local_book.title = remote_data.get("title", local_book.title)
                local_book.author = remote_data.get("author", local_book.author)
                local_book.publisher = remote_data.get("publisher", local_book.publisher)
                local_book.category = remote_data.get("category", local_book.category)
                local_book.subcategory = remote_data.get("subcategory", local_book.subcategory)
                local_book.price = remote_data.get("price", local_book.price)
                local_book.version = remote_data.get("version", local_book.version)

        elif strategy == "RENAME_STOCK":
            new_stock = resolution_data.get("new_stock_number") if resolution_data else None
            if not new_stock:
                raise ValueError("New unique stock number is required for RENAME_STOCK strategy.")
            if local_book:
                local_book.stock_number = new_stock
                local_book.version = (local_book.version or 1) + 1

        elif strategy == "MANUAL":
            fields = resolution_data.get("fields", {}) if resolution_data else {}
            if local_book:
                for k, v in fields.items():
                    if hasattr(local_book, k):
                        setattr(local_book, k, v)
                local_book.version = (local_book.version or 1) + 1

            if remote_db:
                remote_book = remote_db.scalar(
                    select(Book).where(Book.stock_number == conflict.stock_number)
                )
                if remote_book:
                    for k, v in fields.items():
                        if hasattr(remote_book, k):
                            setattr(remote_book, k, v)
                    remote_book.version = (remote_book.version or 1) + 1
                    remote_db.commit()
        else:
            raise ValueError(f"Unknown resolution strategy: {strategy}")

        # Mark conflict resolved
        conflict.is_resolved = True
        conflict.resolution_strategy = strategy
        conflict.resolved_at = utc_now()

        # Update any pending queue items for this stock number to SYNCED
        queue_items = db.scalars(
            select(SyncQueueItem)
            .where(
                SyncQueueItem.status.in_(["CONFLICT", "PENDING"]),
                SyncQueueItem.payload.contains(f'"{conflict.stock_number}"'),
            )
        ).all()
        for qi in queue_items:
            qi.status = "SYNCED"
            qi.synced_at = utc_now()

        db.commit()
        return {
            "status": "resolved",
            "conflict_id": conflict_id,
            "strategy": strategy,
        }
    finally:
        if remote_db:
            remote_db.close()
