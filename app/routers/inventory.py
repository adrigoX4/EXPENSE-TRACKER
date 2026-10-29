from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MovementType, StockMovement, StockReceipt
from app.schemas import (
    InventorySummary,
    MovementCreate,
    MovementOut,
    MovementPage,
    StockReceiptCreate,
    StockReceiptOut,
)
from app.serializers import movement_out, receipt_out
from app.services.inventory import (
    create_manual_movement,
    create_receipt,
    list_movements,
    list_receipts,
)
from app.services.products import inventory_summary

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/summary", response_model=InventorySummary)
def summary(db: Session = Depends(get_db)):
    return inventory_summary(db)


@router.get("/movements", response_model=MovementPage)
def movements(
    product_id: int | None = None,
    movement_type: MovementType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = list_movements(
        db,
        product_id=product_id,
        movement_type=movement_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [movement_out(movement) for movement in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def create_movement(payload: MovementCreate, db: Session = Depends(get_db)):
    movement, created = create_manual_movement(db, payload)
    db.commit()
    db.refresh(movement)
    return movement_out(movement)


@router.get("/receipts")
def receipts(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = list_receipts(db, limit=limit, offset=offset)
    return {
        "items": [receipt_out(receipt) for receipt in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/receipts", response_model=StockReceiptOut, status_code=status.HTTP_201_CREATED)
def add_receipt(payload: StockReceiptCreate, db: Session = Depends(get_db)):
    receipt, created = create_receipt(db, payload)
    db.commit()
    return receipt_out(receipt)
