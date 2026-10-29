from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit, snapshot
from app.database import get_db
from app.models import AuditLog, SyncStatus
from app.schemas import AuditOut, SettingsOut, SettingsUpdate, SyncOperationOut
from app.services.settings_service import get_settings, save_settings
from app.services.sync_service import list_operations

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@router.put("/settings", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    before = get_settings(db)
    updated = save_settings(
        db,
        business_name=payload.business_name,
        payment_methods=payload.payment_methods,
        expense_categories=payload.expense_categories,
        money_in_categories=payload.money_in_categories,
        money_out_categories=payload.money_out_categories,
        default_low_stock_threshold=payload.default_low_stock_threshold,
        opening_cash_balance=payload.opening_cash_balance,
        opening_upi_balance=payload.opening_upi_balance,
        opening_balance_date=payload.opening_balance_date,
        opening_fields=payload.model_fields_set,
        clear_opening_balances=payload.clear_opening_balances,
    )
    audit(
        db,
        entity_type="settings",
        entity_id="app",
        action="updated",
        before=before,
        after=updated,
    )
    db.commit()
    return updated


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(
        db.scalars(
            stmt.order_by(AuditLog.changed_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
        )
    )


@router.get("/sync/operations")
def sync_operations(
    status: SyncStatus | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, counts = list_operations(
        db,
        status=status,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [SyncOperationOut.model_validate(item) for item in items],
        "total": total,
        "counts": counts,
    }
