from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ExpenseCreate, ExpenseOut, ExpensePage, ExpenseUpdate, ExpenseVoid
from app.serializers import expense_out
from app.services.expenses import (
    create_expense,
    get_expense,
    list_expenses,
    update_expense,
    void_expense,
)

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.get("", response_model=ExpensePage)
def index(
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    method: str | None = None,
    include_void: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, totals = list_expenses(
        db,
        search=search,
        date_from=date_from,
        date_to=date_to,
        category=category,
        method=method,
        include_void=include_void,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [expense_out(expense) for expense in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "totals": totals,
    }


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create(payload: ExpenseCreate, db: Session = Depends(get_db)):
    expense, created = create_expense(db, payload)
    return expense_out(expense)


@router.get("/{expense_id}", response_model=ExpenseOut)
def detail(expense_id: int, db: Session = Depends(get_db)):
    return expense_out(get_expense(db, expense_id))


@router.patch("/{expense_id}", response_model=ExpenseOut)
def patch(expense_id: int, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = update_expense(db, expense_id, payload)
    return expense_out(expense)


@router.post("/{expense_id}/void", response_model=ExpenseOut)
def void(expense_id: int, payload: ExpenseVoid, db: Session = Depends(get_db)):
    expense = void_expense(db, expense_id, payload)
    return expense_out(expense)
