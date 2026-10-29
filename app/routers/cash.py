from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.schemas import (
    AdjustmentCreate,
    CashHandoverCreate,
    CashHandoverOut,
    CashOverview,
    CashSessionOut,
    CashSessionUpsert,
    PaymentOut,
)
from app.serializers import handover_out, payment_out
from app.services.cash import (
    add_adjustment,
    cash_overview,
    create_handover,
    get_session,
    list_handovers,
    list_payments,
    list_sessions,
    upsert_session,
)
from app.utils import local_day, utcnow

cash_router = APIRouter(prefix="/api/cash", tags=["cash"])
handover_router = APIRouter(prefix="/api/handovers", tags=["handovers"])
payment_router = APIRouter(prefix="/api/payments", tags=["payments"])


@cash_router.get("/overview", response_model=CashOverview)
def overview(day: date | None = None, db: Session = Depends(get_db)):
    return cash_overview(db, day or local_day(utcnow()))


@cash_router.get("/sessions", response_model=list[CashSessionOut])
def sessions(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return list_sessions(db, date_from=date_from, date_to=date_to)


@cash_router.get("/sessions/{session_date}", response_model=CashSessionOut | None)
def session_detail(session_date: date, db: Session = Depends(get_db)):
    return get_session(db, session_date)


@cash_router.put("/sessions/{session_date}", response_model=CashSessionOut)
def save_session(session_date: date, payload: CashSessionUpsert, db: Session = Depends(get_db)):
    return upsert_session(db, session_date, payload)


@handover_router.get("")
def index_handovers(
    date_from: date | None = None,
    date_to: date | None = None,
    method: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = list_handovers(
        db,
        date_from=date_from,
        date_to=date_to,
        method=method,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [handover_out(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@handover_router.post("", response_model=CashHandoverOut, status_code=status.HTTP_201_CREATED)
def create_handover_route(payload: CashHandoverCreate, db: Session = Depends(get_db)):
    handover, created = create_handover(db, payload)
    return handover_out(handover)


@payment_router.get("")
def index_payments(
    sale_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    method: str | None = None,
    direction: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    from app.models import PaymentDirection

    parsed_direction = None
    if direction:
        try:
            parsed_direction = PaymentDirection(direction)
        except ValueError as exc:
            raise ValidationError("direction must be 'in' or 'out'") from exc
    items, total = list_payments(
        db,
        sale_id=sale_id,
        date_from=date_from,
        date_to=date_to,
        method=method,
        direction=parsed_direction,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [payment_out(payment) for payment in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@payment_router.post("/adjustments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(payload: AdjustmentCreate, db: Session = Depends(get_db)):
    payment, created = add_adjustment(db, payload)
    return payment_out(payment)
