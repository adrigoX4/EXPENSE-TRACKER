from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SyncOperation, SyncStatus
from app.utils import utcnow


def record_sync(
    db: Session,
    *,
    operation_id: str,
    entity_type: str,
    entity_id: int | str | None,
    operation_type: str,
    local_created_at: datetime | None = None,
    status: SyncStatus = SyncStatus.synced,
    error: str | None = None,
) -> SyncOperation:
    existing = db.scalar(select(SyncOperation).where(SyncOperation.operation_id == operation_id))
    if existing:
        existing.attempts += 1
        existing.synced_at = utcnow()
        existing.status = status
        if entity_id is not None:
            existing.entity_id = str(entity_id)
        if error:
            existing.error = error
        return existing

    op = SyncOperation(
        operation_id=operation_id,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        operation_type=operation_type,
        local_created_at=local_created_at,
        synced_at=utcnow() if status == SyncStatus.synced else None,
        status=status,
        attempts=1,
        error=error,
    )
    db.add(op)
    return op


def list_operations(
    db: Session,
    *,
    status: SyncStatus | None = None,
    entity_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SyncOperation], int, dict[str, int]]:
    conditions = []
    if status:
        conditions.append(SyncOperation.status == status)
    if entity_type:
        conditions.append(SyncOperation.entity_type == entity_type)

    stmt = select(SyncOperation)
    count_stmt = select(func.count(SyncOperation.id))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    rows = list(
        db.scalars(
            stmt.order_by(SyncOperation.created_at.desc(), SyncOperation.id.desc()).limit(limit).offset(offset)
        )
    )
    counts = {s.value: 0 for s in SyncStatus}
    for value, count in db.execute(
        select(SyncOperation.status, func.count(SyncOperation.id)).group_by(SyncOperation.status)
    ):
        counts[value.value if hasattr(value, "value") else str(value)] = count
    return rows, total, counts
