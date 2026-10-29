from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import Expense
from app.schemas import ExpenseCreate, ExpenseUpdate, ExpenseVoid
from app.services.settings_service import validate_expense_category, validate_method
from app.utils import money, range_bounds_utc, utcnow

EXPENSE_FIELDS = [
    "occurred_at",
    "category",
    "description",
    "amount",
    "method",
    "paid_to",
    "reference",
    "notes",
    "is_void",
    "version",
]

STOCK_CATEGORY = "inventory_purchase"


def _reject_manual_stock_category(category: str) -> None:
    if category == STOCK_CATEGORY:
        raise ValidationError(
            "Stock purchases are recorded through Inventory → Receive stock so they stay linked to the stock receipt. "
            "Use this form for ordinary operating costs only."
        )


def get_expense(db: Session, expense_id: int) -> Expense:
    expense = db.get(Expense, expense_id)
    if not expense:
        raise NotFoundError("Expense not found")
    return expense


def create_expense(db: Session, payload: ExpenseCreate) -> tuple[Expense, bool]:
    if payload.idempotency_key:
        existing = db.scalar(select(Expense).where(Expense.idempotency_key == payload.idempotency_key))
        if existing:
            return existing, False
    category = validate_expense_category(db, payload.category)
    _reject_manual_stock_category(category)
    method = validate_method(db, payload.method)
    expense = Expense(
        idempotency_key=payload.idempotency_key,
        occurred_at=payload.occurred_at or utcnow(),
        category=category,
        description=payload.description.strip(),
        amount=money(payload.amount),
        method=method,
        paid_to=payload.paid_to,
        reference=payload.reference,
        notes=payload.notes,
        version=1,
    )
    db.add(expense)
    db.flush()
    audit(
        db,
        entity_type="expense",
        entity_id=expense.id,
        action="created",
        after=snapshot(expense, EXPENSE_FIELDS),
    )
    db.commit()
    return expense, True


def update_expense(db: Session, expense_id: int, payload: ExpenseUpdate) -> Expense:
    expense = get_expense(db, expense_id)
    if expense.is_void:
        raise ConflictError("A voided expense cannot be edited.", code="expense_voided")
    if expense.stock_receipt:
        raise ConflictError(
            "This expense was generated from a stock receipt. Edit or correct the stock purchase instead.",
            code="linked_stock_expense",
        )
    if expense.version != payload.version:
        raise ConflictError(
            "This expense was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": snapshot(expense, EXPENSE_FIELDS)},
        )
    before = snapshot(expense, EXPENSE_FIELDS)
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "category" in changes and changes["category"]:
        changes["category"] = validate_expense_category(db, changes["category"])
        if changes["category"] != expense.category:
            _reject_manual_stock_category(changes["category"])
    if "method" in changes and changes["method"]:
        changes["method"] = validate_method(db, changes["method"])
    if "amount" in changes and changes["amount"] is not None:
        changes["amount"] = money(changes["amount"])
    for field, value in changes.items():
        setattr(expense, field, value)
    if not expense.description.strip():
        raise ValidationError("Expense description is required")
    expense.version += 1
    audit(
        db,
        entity_type="expense",
        entity_id=expense.id,
        action="updated",
        before=before,
        after=snapshot(expense, EXPENSE_FIELDS),
    )
    db.commit()
    return expense


def void_expense(db: Session, expense_id: int, payload: ExpenseVoid) -> Expense:
    expense = get_expense(db, expense_id)
    if expense.is_void:
        raise ConflictError("This expense is already voided.", code="already_voided")
    if expense.stock_receipt:
        raise ConflictError(
            "This expense belongs to a stock receipt and cannot be voided here.",
            code="linked_stock_expense",
        )
    if payload.version is not None and expense.version != payload.version:
        raise ConflictError(
            "This expense was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": snapshot(expense, EXPENSE_FIELDS)},
        )
    before = snapshot(expense, EXPENSE_FIELDS)
    expense.is_void = True
    expense.void_reason = payload.reason
    expense.voided_at = utcnow()
    expense.version += 1
    audit(
        db,
        entity_type="expense",
        entity_id=expense.id,
        action="voided",
        before=before,
        after=snapshot(expense, EXPENSE_FIELDS),
        note=payload.reason,
    )
    db.commit()
    return expense


def list_expenses(
    db: Session,
    *,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    method: str | None = None,
    include_void: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Expense], int, dict]:
    conditions = []
    if not include_void:
        conditions.append(Expense.is_void.is_(False))
    if search:
        term = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Expense.description).like(term),
                func.lower(func.coalesce(Expense.notes, "")).like(term),
                func.lower(func.coalesce(Expense.reference, "")).like(term),
                func.lower(func.coalesce(Expense.paid_to, "")).like(term),
            )
        )
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(Expense.occurred_at >= start)
    if end:
        conditions.append(Expense.occurred_at <= end)
    if category:
        conditions.append(Expense.category == category)
    if method:
        conditions.append(Expense.method == method)

    stmt = select(Expense)
    count_stmt = select(func.count(Expense.id))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(stmt.order_by(Expense.occurred_at.desc(), Expense.id.desc()).limit(limit).offset(offset))
    )
    sum_stmt = select(
        func.coalesce(func.sum(Expense.amount), 0),
        func.count(Expense.id),
    ).where(Expense.is_void.is_(False))
    if conditions:
        sum_stmt = sum_stmt.where(*conditions)
    amount_sum, count = db.execute(sum_stmt).one()
    return items, total, {"amount": money(amount_sum), "count": count}
