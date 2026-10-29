from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    CashHandover,
    Expense,
    MoneyDirection,
    MoneyTransaction,
    Payment,
    PaymentDirection,
    PaymentKind,
    Sale,
    StockReceipt,
)
from app.schemas import (
    MoneyTransactionCreate,
    MoneyTransactionUpdate,
    MoneyTransactionVoid,
)
from app.services.ranges import resolve_range
from app.services.settings_service import (
    TRANSFER_CATEGORY,
    get_settings,
    money_category_label,
    validate_method,
    validate_money_category,
)
from app.utils import day_bounds_utc, local_day, money, month_bounds, utcnow

ZERO = Decimal("0.00")
SOURCE_RANK = {"payment": 0, "expense": 1, "stock_purchase": 2, "handover": 3, "money": 4}
MONEY_FIELDS = [
    "direction",
    "amount",
    "person",
    "category",
    "method",
    "occurred_at",
    "description",
    "reference",
    "notes",
    "is_void",
    "version",
]


def _opening_config(db: Session) -> dict:
    data = get_settings(db)
    cash = money(data.get("opening_cash_balance")) if data.get("opening_cash_balance") is not None else ZERO
    upi = money(data.get("opening_upi_balance")) if data.get("opening_upi_balance") is not None else ZERO
    raw_date = data.get("opening_balance_date")
    opening_date: date | None = None
    if raw_date:
        try:
            opening_date = date.fromisoformat(str(raw_date))
        except ValueError:
            opening_date = None
    start_dt = day_bounds_utc(opening_date)[0] if opening_date else None
    complete = data.get("opening_cash_balance") is not None and data.get("opening_upi_balance") is not None
    return {
        "cash": cash,
        "upi": upi,
        "date": opening_date,
        "start": start_dt,
        "complete": complete,
    }


def _add_balance(
    bucket: dict, method: str, direction: str, amount: Decimal, category: str | None = None
) -> None:
    if category == TRANSFER_CATEGORY:
        if method == "cash":
            bucket["cash"] -= amount
            bucket["upi"] += amount
        elif method == "upi":
            bucket["upi"] -= amount
            bucket["cash"] += amount
        return
    sign = 1 if direction == "in" else -1
    if method == "cash":
        bucket["cash"] += amount * sign
    elif method == "upi":
        bucket["upi"] += amount * sign
    else:
        bucket["other"] += amount * sign


def _load_rows(db: Session) -> list[dict]:
    settings = get_settings(db)
    inventory_category = settings.get("inventory_category", "inventory_purchase")
    rows: list[dict] = []

    payments = db.scalars(
        select(Payment).options(selectinload(Payment.sale).selectinload(Sale.customer))
    ).all()
    for payment in payments:
        sale = payment.sale
        person = None
        if sale:
            person = sale.customer.name if sale.customer else sale.customer_ref
        direction = "in" if payment.direction == PaymentDirection.inflow else "out"
        if payment.kind == PaymentKind.sale_payment:
            category = "customer_payment"
            description = f"Payment for sale #{payment.sale_id}"
        elif payment.kind == PaymentKind.refund:
            category = "refund"
            description = f"Refund for sale #{payment.sale_id}"
        else:
            category = "adjustment"
            description = "Cash / UPI adjustment"
        rows.append(
            {
                "key": f"payment:{payment.id}",
                "source": "payment",
                "record_id": payment.id,
                "occurred_at": payment.paid_at,
                "direction": direction,
                "amount": money(payment.amount),
                "method": payment.method,
                "person": person,
                "category": category,
                "category_label": money_category_label(category),
                "description": description,
                "reference": payment.reference,
                "notes": payment.notes,
                "sale_id": payment.sale_id,
                "sale_external_order_id": sale.external_order_id if sale else None,
                "expense_id": None,
                "receipt_id": None,
                "handover_id": None,
                "money_id": None,
                "is_void": False,
                "editable": False,
                "voidable": False,
                "version": None,
                "link": f"/sales/{payment.sale_id}" if payment.sale_id else None,
                "created_at": payment.created_at,
            }
        )

    expenses = db.scalars(select(Expense).options(selectinload(Expense.stock_receipt))).all()
    for expense in expenses:
        receipt: StockReceipt | None = expense.stock_receipt
        is_stock = receipt is not None or expense.category == inventory_category
        source = "stock_purchase" if is_stock else "expense"
        person = expense.paid_to or (receipt.supplier_ref if receipt else None)
        rows.append(
            {
                "key": f"expense:{expense.id}",
                "source": source,
                "record_id": expense.id,
                "occurred_at": expense.occurred_at,
                "direction": "out",
                "amount": money(expense.amount),
                "method": expense.method,
                "person": person,
                "category": expense.category,
                "category_label": "Stock purchase" if is_stock else money_category_label(expense.category),
                "description": expense.description,
                "reference": expense.reference,
                "notes": expense.notes,
                "sale_id": None,
                "sale_external_order_id": None,
                "expense_id": expense.id,
                "receipt_id": receipt.id if receipt else None,
                "handover_id": None,
                "money_id": None,
                "is_void": expense.is_void,
                "editable": not expense.is_void and receipt is None,
                "voidable": not expense.is_void and receipt is None,
                "version": expense.version,
                "link": f"/expenses?focus={expense.id}",
                "created_at": expense.created_at,
            }
        )

    handovers = db.scalars(select(CashHandover)).all()
    for handover in handovers:
        rows.append(
            {
                "key": f"handover:{handover.id}",
                "source": "handover",
                "record_id": handover.id,
                "occurred_at": handover.handed_at,
                "direction": "out",
                "amount": money(handover.amount),
                "method": handover.method,
                "person": handover.recipient,
                "category": "cash_handover",
                "category_label": "Cash handover",
                "description": "Cash handed over (custody transfer, not an expense)",
                "reference": handover.reference,
                "notes": handover.notes,
                "sale_id": None,
                "sale_external_order_id": None,
                "expense_id": None,
                "receipt_id": None,
                "handover_id": handover.id,
                "money_id": None,
                "is_void": False,
                "editable": False,
                "voidable": False,
                "version": None,
                "link": None,
                "created_at": handover.created_at,
            }
        )

    transactions = db.scalars(select(MoneyTransaction)).all()
    for transaction in transactions:
        rows.append(
            {
                "key": f"money:{transaction.id}",
                "source": "money",
                "record_id": transaction.id,
                "occurred_at": transaction.occurred_at,
                "direction": "in" if transaction.direction == MoneyDirection.inflow else "out",
                "amount": money(transaction.amount),
                "method": transaction.method,
                "person": transaction.person,
                "category": transaction.category,
                "category_label": money_category_label(transaction.category),
                "description": transaction.description,
                "reference": transaction.reference,
                "notes": transaction.notes,
                "sale_id": None,
                "sale_external_order_id": None,
                "expense_id": None,
                "receipt_id": None,
                "handover_id": None,
                "money_id": transaction.id,
                "is_void": transaction.is_void,
                "editable": not transaction.is_void,
                "voidable": not transaction.is_void,
                "version": transaction.version,
                "link": f"/money-history?focus={transaction.id}",
                "created_at": transaction.created_at,
            }
        )

    rows.sort(key=lambda row: (row["occurred_at"], SOURCE_RANK.get(row["source"], 9), row["record_id"]))
    return rows


def _apply_running_balances(rows: list[dict], opening: dict) -> tuple[Decimal, Decimal]:
    cash = opening["cash"]
    upi = opening["upi"]
    start = opening["start"]
    for row in rows:
        if start is not None and row["occurred_at"] < start:
            row["cash_balance_after"] = None
            row["upi_balance_after"] = None
            row["other_balance_after"] = None
            continue
        if row["category"] == TRANSFER_CATEGORY:
            if row["method"] == "cash":
                cash -= row["amount"]
                upi += row["amount"]
            elif row["method"] == "upi":
                upi -= row["amount"]
                cash += row["amount"]
        elif row["method"] == "cash":
            cash += row["amount"] if row["direction"] == "in" else -row["amount"]
        elif row["method"] == "upi":
            upi += row["amount"] if row["direction"] == "in" else -row["amount"]
        row["cash_balance_after"] = money(cash)
        row["upi_balance_after"] = money(upi)
        row["other_balance_after"] = None
    return money(cash), money(upi)


def _range_bounds(
    range_name: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None, date | None, date | None, str]:
    name = (range_name or "month").lower()
    if name in {"all", "all_time"}:
        return None, None, None, None, "All time"
    start_day, end_day, label = resolve_range(name, date_from, date_to)
    start = day_bounds_utc(start_day)[0]
    end = day_bounds_utc(end_day)[1]
    return start, end, start_day, end_day, label


def _matches(row: dict, **filters) -> bool:
    search = (filters.get("search") or "").strip().lower()
    direction = filters.get("direction")
    category = filters.get("category")
    method = filters.get("method")
    source = filters.get("source")
    if direction and row["direction"] != direction:
        return False
    if category and row["category"] != category:
        return False
    if method and row["method"] != method:
        return False
    if source and row["source"] != source:
        return False
    if search:
        haystack = " ".join(
            str(value)
            for value in (
                row.get("person"),
                row.get("amount"),
                row.get("description"),
                row.get("reference"),
                row.get("notes"),
                row.get("category_label"),
                row.get("sale_external_order_id"),
                f"sale {row['sale_id']}" if row.get("sale_id") else None,
            )
            if value is not None and value != ""
        ).lower()
        if search not in haystack:
            return False
    return True


def _in_range(row: dict, start: datetime | None, end: datetime | None) -> bool:
    if start and row["occurred_at"] < start:
        return False
    if end and row["occurred_at"] > end:
        return False
    return True


def _summary(
    all_rows: list[dict],
    filtered_rows: list[dict],
    opening: dict,
    start: datetime | None,
    end: datetime | None,
    label: str,
    date_from: date | None,
    date_to: date | None,
) -> dict:
    totals = {
        "money_in": ZERO,
        "money_out": ZERO,
        "cash_in": ZERO,
        "cash_out": ZERO,
        "upi_in": ZERO,
        "upi_out": ZERO,
        "other_in": ZERO,
        "other_out": ZERO,
        "sale_payments_in": ZERO,
        "ordinary_expenses": ZERO,
        "stock_purchases": ZERO,
        "count": 0,
    }
    for row in filtered_rows:
        if row["is_void"]:
            continue
        amount = row["amount"]
        direction = row["direction"]
        totals["count"] += 1
        if row["category"] == TRANSFER_CATEGORY:
            if direction == "out" and row["method"] == "cash":
                totals["cash_out"] += amount
                totals["upi_in"] += amount
            elif direction == "out" and row["method"] == "upi":
                totals["upi_out"] += amount
                totals["cash_in"] += amount
            continue
        if direction == "in":
            totals["money_in"] += amount
            if row["method"] == "cash":
                totals["cash_in"] += amount
            elif row["method"] == "upi":
                totals["upi_in"] += amount
            else:
                totals["other_in"] += amount
            if row["source"] == "payment" and row["category"] == "customer_payment":
                totals["sale_payments_in"] += amount
        else:
            totals["money_out"] += amount
            if row["method"] == "cash":
                totals["cash_out"] += amount
            elif row["method"] == "upi":
                totals["upi_out"] += amount
            else:
                totals["other_out"] += amount
            if row["source"] == "expense":
                totals["ordinary_expenses"] += amount
            elif row["source"] == "stock_purchase":
                totals["stock_purchases"] += amount

    prefix = {"cash": opening["cash"], "upi": opening["upi"], "other": ZERO}
    for row in all_rows:
        if row["is_void"] or not _in_range(row, opening["start"], None):
            continue
        if start is None or row["occurred_at"] >= start:
            continue
        _add_balance(prefix, row["method"], row["direction"], row["amount"], row["category"])

    closing = dict(prefix)
    for row in all_rows:
        if row["is_void"] or not _in_range(row, opening["start"], None):
            continue
        if start and row["occurred_at"] < start:
            continue
        if end and row["occurred_at"] > end:
            continue
        _add_balance(closing, row["method"], row["direction"], row["amount"], row["category"])

    current = {"cash": opening["cash"], "upi": opening["upi"], "other": ZERO}
    for row in all_rows:
        if row["is_void"] or not _in_range(row, opening["start"], None):
            continue
        _add_balance(current, row["method"], row["direction"], row["amount"], row["category"])

    return {
        "label": label,
        "date_from": date_from,
        "date_to": date_to,
        "money_in": money(totals["money_in"]),
        "money_out": money(totals["money_out"]),
        "cash_in": money(totals["cash_in"]),
        "cash_out": money(totals["cash_out"]),
        "upi_in": money(totals["upi_in"]),
        "upi_out": money(totals["upi_out"]),
        "other_in": money(totals["other_in"]),
        "other_out": money(totals["other_out"]),
        "count": totals["count"],
        "sale_payments_in": money(totals["sale_payments_in"]),
        "other_money_in": money(totals["money_in"] - totals["sale_payments_in"]),
        "ordinary_expenses": money(totals["ordinary_expenses"]),
        "stock_purchases": money(totals["stock_purchases"]),
        "opening_cash": money(prefix["cash"]),
        "opening_upi": money(prefix["upi"]),
        "closing_cash": money(closing["cash"]),
        "closing_upi": money(closing["upi"]),
        "current_cash": money(current["cash"]),
        "current_upi": money(current["upi"]),
        "balance_complete": bool(opening["complete"]),
        "opening_effective_date": opening["date"],
    }


def _daily_rows(filtered_rows: list[dict], start: datetime | None, end: datetime | None) -> list[dict]:
    buckets: dict[date, dict] = {}
    for row in filtered_rows:
        if row["is_void"]:
            continue
        day = local_day(row["occurred_at"])
        bucket = buckets.setdefault(
            day,
            {
                "date": day,
                "money_in": ZERO,
                "money_out": ZERO,
                "cash_in": ZERO,
                "cash_out": ZERO,
                "upi_in": ZERO,
                "upi_out": ZERO,
                "count": 0,
            },
        )
        bucket["count"] += 1
        if row["category"] == TRANSFER_CATEGORY:
            if row["direction"] == "out" and row["method"] == "cash":
                bucket["cash_out"] += row["amount"]
                bucket["upi_in"] += row["amount"]
            elif row["direction"] == "out" and row["method"] == "upi":
                bucket["upi_out"] += row["amount"]
                bucket["cash_in"] += row["amount"]
        elif row["direction"] == "in":
            bucket["money_in"] += row["amount"]
            if row["method"] == "cash":
                bucket["cash_in"] += row["amount"]
            elif row["method"] == "upi":
                bucket["upi_in"] += row["amount"]
        else:
            bucket["money_out"] += row["amount"]
            if row["method"] == "cash":
                bucket["cash_out"] += row["amount"]
            elif row["method"] == "upi":
                bucket["upi_out"] += row["amount"]
    if start and end:
        first = local_day(start)
        last = local_day(end)
        span = (last - first).days + 1
        if span <= 62:
            days = [first + timedelta(days=index) for index in range(span)]
        else:
            days = sorted(buckets)
    else:
        days = sorted(buckets)
    result = []
    for day in days:
        bucket = buckets.get(day)
        if not bucket:
            bucket = {
                "date": day,
                "money_in": ZERO,
                "money_out": ZERO,
                "cash_in": ZERO,
                "cash_out": ZERO,
                "upi_in": ZERO,
                "upi_out": ZERO,
                "count": 0,
            }
        result.append(
            {
                "date": day,
                "money_in": money(bucket["money_in"]),
                "money_out": money(bucket["money_out"]),
                "cash_in": money(bucket["cash_in"]),
                "cash_out": money(bucket["cash_out"]),
                "upi_in": money(bucket["upi_in"]),
                "upi_out": money(bucket["upi_out"]),
                "count": bucket["count"],
            }
        )
    return result


def ledger(
    db: Session,
    *,
    range_name: str | None = "month",
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    direction: str | None = None,
    category: str | None = None,
    method: str | None = None,
    source: str | None = None,
    include_void: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if direction and direction not in {"in", "out"}:
        raise ValidationError("direction must be 'in' or 'out'")
    start, end, start_day, end_day, label = _range_bounds(range_name, date_from, date_to)
    opening = _opening_config(db)
    rows = _load_rows(db)
    _apply_running_balances(rows, opening)

    filtered = [
        row
        for row in rows
        if _in_range(row, start, end) and (include_void or not row["is_void"])
    ]
    filtered = [
        row
        for row in filtered
        if _matches(
            row,
            search=search,
            direction=direction,
            category=category,
            method=method,
            source=source,
        )
    ]
    summary = _summary(rows, filtered, opening, start, end, label, start_day, end_day)
    daily = _daily_rows(filtered, start, end)
    total = len(filtered)
    display = sorted(
        filtered,
        key=lambda row: (row["occurred_at"], SOURCE_RANK.get(row["source"], 9), row["record_id"]),
        reverse=True,
    )
    page = display[offset : offset + limit]
    return {
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": summary,
        "daily": daily,
    }


def period_money_summary(db: Session, date_from: date, date_to: date) -> dict:
    start, end = day_bounds_utc(date_from)[0], day_bounds_utc(date_to)[1]
    opening = _opening_config(db)
    rows = _load_rows(db)
    _apply_running_balances(rows, opening)
    in_range = [row for row in rows if _in_range(row, start, end) and not row["is_void"]]
    return _summary(rows, in_range, opening, start, end, "Custom", date_from, date_to)


def current_balances(db: Session) -> dict:
    opening = _opening_config(db)
    rows = _load_rows(db)
    cash, upi = _apply_running_balances(rows, opening)
    return {
        "cash": cash,
        "upi": upi,
        "opening_cash": opening["cash"],
        "opening_upi": opening["upi"],
        "opening_effective_date": opening["date"],
        "balance_complete": opening["complete"],
    }


def monthly_summary(db: Session, year: int) -> list[dict]:
    rows = [row for row in _load_rows(db) if not row["is_void"]]
    today = local_day(utcnow())
    output = []
    for month in range(1, 13):
        first, last = month_bounds(year, month)
        if first > today:
            break
        if last > today:
            last = today
        start = day_bounds_utc(first)[0]
        end = day_bounds_utc(last)[1]
        totals = {
            "money_in": ZERO,
            "money_out": ZERO,
            "cash_in": ZERO,
            "cash_out": ZERO,
            "upi_in": ZERO,
            "upi_out": ZERO,
            "count": 0,
        }
        for row in rows:
            if not _in_range(row, start, end):
                continue
            totals["count"] += 1
            if row["category"] == TRANSFER_CATEGORY:
                if row["direction"] == "out" and row["method"] == "cash":
                    totals["cash_out"] += row["amount"]
                    totals["upi_in"] += row["amount"]
                elif row["direction"] == "out" and row["method"] == "upi":
                    totals["upi_out"] += row["amount"]
                    totals["cash_in"] += row["amount"]
            elif row["direction"] == "in":
                totals["money_in"] += row["amount"]
                if row["method"] == "cash":
                    totals["cash_in"] += row["amount"]
                elif row["method"] == "upi":
                    totals["upi_in"] += row["amount"]
            else:
                totals["money_out"] += row["amount"]
                if row["method"] == "cash":
                    totals["cash_out"] += row["amount"]
                elif row["method"] == "upi":
                    totals["upi_out"] += row["amount"]
        output.append(
            {
                "month": month,
                "label": calendar.month_name[month],
                "money_in": money(totals["money_in"]),
                "money_out": money(totals["money_out"]),
                "cash_in": money(totals["cash_in"]),
                "cash_out": money(totals["cash_out"]),
                "upi_in": money(totals["upi_in"]),
                "upi_out": money(totals["upi_out"]),
                "count": totals["count"],
            }
        )
    return output


def get_transaction(db: Session, transaction_id: int) -> MoneyTransaction:
    transaction = db.get(MoneyTransaction, transaction_id)
    if not transaction:
        raise NotFoundError("Money transaction not found")
    return transaction


def create_transaction(db: Session, payload: MoneyTransactionCreate) -> tuple[MoneyTransaction, bool]:
    if payload.idempotency_key:
        existing = db.scalar(
            select(MoneyTransaction).where(MoneyTransaction.idempotency_key == payload.idempotency_key)
        )
        if existing:
            return existing, False
    direction = MoneyDirection(payload.direction)
    category = validate_money_category(db, direction, payload.category)
    method = validate_method(db, payload.method)
    if category == TRANSFER_CATEGORY and method not in {"cash", "upi"}:
        raise ValidationError("A transfer can only move money between cash and UPI.")
    transaction = MoneyTransaction(
        idempotency_key=payload.idempotency_key,
        direction=direction,
        amount=money(payload.amount),
        person=payload.person,
        category=category,
        method=method,
        occurred_at=payload.occurred_at or utcnow(),
        description=payload.description,
        reference=payload.reference,
        notes=payload.notes,
        version=1,
    )
    db.add(transaction)
    db.flush()
    audit(
        db,
        entity_type="money_transaction",
        entity_id=transaction.id,
        action="created",
        after=snapshot(transaction, MONEY_FIELDS),
    )
    db.commit()
    return transaction, True


def update_transaction(
    db: Session, transaction_id: int, payload: MoneyTransactionUpdate
) -> MoneyTransaction:
    transaction = get_transaction(db, transaction_id)
    if transaction.is_void:
        raise ConflictError("A voided money transaction cannot be edited.", code="money_voided")
    if transaction.version != payload.version:
        raise ConflictError(
            "This money transaction was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": snapshot(transaction, MONEY_FIELDS)},
        )
    before = snapshot(transaction, MONEY_FIELDS)
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    direction = MoneyDirection(changes.get("direction") or transaction.direction)
    if "direction" in changes:
        transaction.direction = direction
    if "category" in changes or "direction" in changes:
        category = changes.get("category") or transaction.category
        transaction.category = validate_money_category(db, direction, category)
    if "method" in changes:
        transaction.method = validate_method(db, changes["method"])
    if "amount" in changes and changes["amount"] is not None:
        transaction.amount = money(changes["amount"])
    for field in ("person", "occurred_at", "description", "reference", "notes"):
        if field in changes:
            setattr(transaction, field, changes[field])
    if not transaction.description.strip():
        raise ValidationError("Description is required")
    if transaction.category == TRANSFER_CATEGORY and transaction.method not in {"cash", "upi"}:
        raise ValidationError("A transfer can only move money between cash and UPI.")
    transaction.version += 1
    audit(
        db,
        entity_type="money_transaction",
        entity_id=transaction.id,
        action="updated",
        before=before,
        after=snapshot(transaction, MONEY_FIELDS),
        note="Correction saved; the original values remain in this audit trail.",
    )
    db.commit()
    return transaction


def void_transaction(
    db: Session, transaction_id: int, payload: MoneyTransactionVoid
) -> MoneyTransaction:
    transaction = get_transaction(db, transaction_id)
    if transaction.is_void:
        raise ConflictError("This money transaction is already voided.", code="already_voided")
    if payload.version is not None and transaction.version != payload.version:
        raise ConflictError(
            "This money transaction was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": snapshot(transaction, MONEY_FIELDS)},
        )
    before = snapshot(transaction, MONEY_FIELDS)
    transaction.is_void = True
    transaction.void_reason = payload.reason
    transaction.voided_at = utcnow()
    transaction.version += 1
    audit(
        db,
        entity_type="money_transaction",
        entity_id=transaction.id,
        action="voided",
        before=before,
        after=snapshot(transaction, MONEY_FIELDS),
        note=payload.reason,
    )
    db.commit()
    return transaction
