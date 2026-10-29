from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DeliveryStatus
from app.schemas import DeliveryCreate, DeliveryPage, DeliveryRowOut, DeliveryUpdate
from app.serializers import delivery_row_out
from app.services.deliveries import (
    create_delivery,
    get_delivery,
    list_deliveries,
    update_delivery,
)

router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])


@router.get("", response_model=DeliveryPage)
def index(
    status_filter: DeliveryStatus | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, counts = list_deliveries(
        db,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [delivery_row_out(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "counts": counts,
    }


@router.post("", response_model=DeliveryRowOut, status_code=status.HTTP_201_CREATED)
def create(payload: DeliveryCreate, db: Session = Depends(get_db)):
    delivery, created = create_delivery(db, payload)
    return delivery_row_out(get_delivery(db, delivery.id))


@router.get("/{delivery_id}", response_model=DeliveryRowOut)
def detail(delivery_id: int, db: Session = Depends(get_db)):
    return delivery_row_out(get_delivery(db, delivery_id))


@router.patch("/{delivery_id}", response_model=DeliveryRowOut)
def patch(delivery_id: int, payload: DeliveryUpdate, db: Session = Depends(get_db)):
    delivery = update_delivery(db, delivery_id, payload)
    return delivery_row_out(delivery)
