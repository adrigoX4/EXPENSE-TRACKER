from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    LedgerPage,
    MoneyMonthlyOut,
    MoneySummaryOut,
    MoneyTransactionCreate,
    MoneyTransactionOut,
    MoneyTransactionUpdate,
    MoneyTransactionVoid,
)
from app.serializers import money_transaction_out
from app.services.money import (
    ledger,
    monthly_summary,
    create_transaction,
    get_transaction,
    update_transaction,
    void_transaction,
)
from app.utils import local_day, utcnow

router = APIRouter(prefix="/api/money", tags=["money"])


@router.get("/ledger", response_model=LedgerPage)
def ledger_view(
    range_name: str | None = Query(default="month", alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    direction: str | None = None,
    category: str | None = None,
    method: str | None = None,
    source: str | None = None,
    include_void: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return ledger(
        db,
        range_name=range_name,
        date_from=date_from,
        date_to=date_to,
        search=search,
        direction=direction,
        category=category,
        method=method,
        source=source,
        include_void=include_void,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=MoneySummaryOut)
def summary_view(
    range_name: str | None = Query(default="month", alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    direction: str | None = None,
    category: str | None = None,
    method: str | None = None,
    source: str | None = None,
    include_void: bool = False,
    db: Session = Depends(get_db),
):
    return ledger(
        db,
        range_name=range_name,
        date_from=date_from,
        date_to=date_to,
        search=search,
        direction=direction,
        category=category,
        method=method,
        source=source,
        include_void=include_void,
        limit=1,
        offset=0,
    )["summary"]


@router.get("/monthly", response_model=MoneyMonthlyOut)
def monthly_view(year: int | None = None, db: Session = Depends(get_db)):
    if year is None:
        year = local_day(utcnow()).year
    return {"year": year, "months": monthly_summary(db, year)}


@router.get("/transactions/{transaction_id}", response_model=MoneyTransactionOut)
def transaction_detail(transaction_id: int, db: Session = Depends(get_db)):
    return money_transaction_out(get_transaction(db, transaction_id))


@router.post(
    "/transactions",
    response_model=MoneyTransactionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction_route(
    payload: MoneyTransactionCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    if idempotency_key and not payload.idempotency_key:
        payload.idempotency_key = idempotency_key
    transaction, created = create_transaction(db, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    else:
        response.headers["Location"] = f"/api/money/transactions/{transaction.id}"
    return money_transaction_out(transaction)


@router.patch("/transactions/{transaction_id}", response_model=MoneyTransactionOut)
def update_transaction_route(
    transaction_id: int,
    payload: MoneyTransactionUpdate,
    db: Session = Depends(get_db),
):
    return money_transaction_out(update_transaction(db, transaction_id, payload))


@router.post("/transactions/{transaction_id}/void", response_model=MoneyTransactionOut)
def void_transaction_route(
    transaction_id: int,
    payload: MoneyTransactionVoid,
    db: Session = Depends(get_db),
):
    return money_transaction_out(void_transaction(db, transaction_id, payload))
