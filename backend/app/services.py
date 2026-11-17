import json
import uuid
from sqlalchemy.orm import Session
from .models import AuditLog, Book, SyncQueueItem


def missing_fields(book: Book) -> list[str]:
    missing = []
    for field, label in [
        (book.author, "author"),
        (book.publisher, "publisher"),
        (book.category, "category"),
        (book.subcategory, "subcategory"),
        (book.price, "price"),
    ]:
        if field is None or (isinstance(field, str) and not field.strip()):
            missing.append(label)
    return missing


def book_to_dict(book: Book) -> dict:
    data = {column.name: getattr(book, column.name) for column in Book.__table__.columns}
    missing = missing_fields(book)
    data["is_complete"] = len(missing) == 0
    data["missing_fields"] = missing
    return data


def log_action(
    db: Session,
    action: str,
    entity_id: int | None,
    details: dict,
    actor: str = "system",
    actor_role: str = "librarian",
    device_id: str | None = None,
    entity_type: str = "book",
):
    db.add(AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=json.dumps(details, ensure_ascii=False, default=str),
        actor=actor,
        actor_role=actor_role,
        device_id=device_id,
    ))


def enqueue_change(
    db: Session,
    operation: str,
    entity_type: str,
    entity_id: int | None,
    payload: dict,
    device_id: str = "device-local",
    change_id: str | None = None,
) -> SyncQueueItem:
    """
    Enqueue an offline change into the sync outbox queue with an idempotency key.
    Safe and non-blocking in offline / local-only mode.
    """
    if not change_id:
        change_id = str(uuid.uuid4())
    item = SyncQueueItem(
        change_id=change_id,
        device_id=device_id or "device-local",
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        status="PENDING",
    )
    db.add(item)
    return item

