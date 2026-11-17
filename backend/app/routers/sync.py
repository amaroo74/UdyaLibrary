import json
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth.dependencies import (
    get_authenticated_device_id,
    require_any_authenticated,
    require_librarian,
)
from ..database import get_db
from ..models import SyncConflict, User
from ..sync.service import get_sync_status, resolve_conflict, sync_two_way

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncTriggerRequest(BaseModel):
    remote_url: str | None = None


class ConflictResolveRequest(BaseModel):
    strategy: str  # 'KEEP_LOCAL', 'KEEP_REMOTE', 'RENAME_STOCK', 'MANUAL'
    new_stock_number: str | None = None
    fields: dict[str, Any] | None = None
    remote_url: str | None = None


@router.get("/status")
def sync_status(
    x_device_id: str | None = Header(default=None),
    current_user: User = Depends(require_any_authenticated),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    """
    Check cloud sync configuration, pending offline queue length, and unresolved conflict counts.
    """
    return get_sync_status(db, device_id=device_id or x_device_id or "device-local")


@router.post("/trigger")
def trigger_sync(
    payload: SyncTriggerRequest | None = None,
    x_device_id: str | None = Header(default=None),
    current_user: User = Depends(require_librarian),
    device_id: str = Depends(get_authenticated_device_id),
    db: Session = Depends(get_db),
):
    """
    Execute two-way synchronization:
    1. Pushes local queued changes to remote PostgreSQL cloud database.
    2. Pulls remote updates into local SQLite database.
    3. Detects conflicts without silent overwrites.
    """
    remote_override = payload.remote_url if payload else None

    try:
        return sync_two_way(
            db,
            remote_url=remote_override,
            device_id=device_id or x_device_id or "device-local",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synchronization failed: {str(e)}")


@router.get("/conflicts")
def list_conflicts(
    current_user: User = Depends(require_librarian),
    db: Session = Depends(get_db),
):
    """
    List all detected unresolved synchronization conflicts.
    """
    conflicts = db.scalars(
        select(SyncConflict)
        .where(SyncConflict.is_resolved.is_(False))
        .order_by(SyncConflict.created_at.desc())
    ).all()

    return [
        {
            "id": c.id,
            "conflict_id": c.conflict_id,
            "device_id": c.device_id,
            "entity_type": c.entity_type,
            "stock_number": c.stock_number,
            "conflict_type": c.conflict_type,
            "local_data": json.loads(c.local_data or "{}"),
            "remote_data": json.loads(c.remote_data or "{}"),
            "is_resolved": c.is_resolved,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in conflicts
    ]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_sync_conflict(
    conflict_id: str,
    payload: ConflictResolveRequest,
    current_user: User = Depends(require_librarian),
    db: Session = Depends(get_db),
):
    """
    Safely resolve a synchronization conflict.
    Never silently overwrites data. Supported strategies: KEEP_LOCAL, KEEP_REMOTE, RENAME_STOCK, MANUAL.
    """
    resolution_data = {}
    if payload.new_stock_number:
        resolution_data["new_stock_number"] = payload.new_stock_number
    if payload.fields:
        resolution_data["fields"] = payload.fields

    try:
        return resolve_conflict(
            db=db,
            conflict_id=conflict_id,
            strategy=payload.strategy,
            resolution_data=resolution_data,
            remote_url=payload.remote_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conflict resolution failed: {str(e)}")
