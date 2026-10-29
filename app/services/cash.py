from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    CashHandover,
    CashSession,
    Expense,
    Payment,
    PaymentDirection,
    PaymentKind,
    Sale,
    SaleStatus,
)
from app.schemas import AdjustmentCreate, CashHandoverCreate, CashSessionUpsert, PaymentCreate
from app.services.settings_service import allowed_methods, default_payment_method, validate_method
from app.utils import day_bounds_utc, money, range_bounds_utc, utcnow

ZERO = Decimal("0.00")


def _payment_totals(db: Session, day: date):
    start, end = day_bounds_utc(day)
    rows = db.execute(
        select(Payment.method, Payment.direction, func.sum(Payment.amount), func.count(Payment.id))
        .where(Payment.paid_at >= start, Payment.paid_at <= end)
        .group_by(Payment.method, Payment.direction)
    ).all()
    by_method: dict[str, dict[str, Decimal]] = {}
    total_in = ZERO
    total_out = ZERO
    count = 0
    for method, direction, amount, row_count in rows:
        amount = money(amount)
        bucket = by_method.setdefault(method, {"in": ZERO, "out": ZERO})
        if direction == PaymentDirection.inflow:
            bucket["in"] += amount
            total_in += amount
        else:
            bucket["out"] += amount
            total_out += amount
        count += row_count
    return by_method, money(total_in), money(total_out), count


def _cash_expenses(db: Session, day: date) -> Decimal:
    start, end = day_bounds_utc(day)
    value = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.is_void.is_(False),
            Expense.method == "cash",
            Expense.occurred_at >= start,
            Expense.occurred_at <= end,
        )
    )
    return money(value)


def _handover_total(db: Session, day: date, *, cash_only: bool = True) -> Decimal:
    start, end = day_bounds_utc(day)
    stmt = select(func.coalesce(func.sum(CashHandover.amount), 0)).where(
        CashHandover.handed_at >= start,
        CashHandover.handed_at <= end,
    )
    if cash_only:
        stmt = stmt.where(CashHandover.method == "cash")
    return money(db.scalar(stmt))


def pending_balances(db: Session) -> Decimal:
    due = Sale.total - Sale.returned_value - (Sale.amount_paid - Sale.refunded_amount)
    value = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (and_(Sale.status == SaleStatus.completed, due > 0), due),
                        else_=0,
                    )
                ),
                0,
            )
        )
    )
    return money(value)


def get_session(db: Session, session_date: date) -> CashSession | None:
    return db.scalar(select(CashSession).where(CashSession.session_date == session_date))


def cash_overview(db: Session, day: date) -> dict:
    by_method, total_in, total_out, payment_count = _payment_totals(db, day)
    cash_in = money(by_method.get("cash", {}).get("in", ZERO))
    upi_in = money(by_method.get("upi", {}).get("in", ZERO))
    other_in = money(total_in - cash_in - upi_in)
    cash_refunds = money(by_method.get("cash", {}).get("out", ZERO))
    cash_expenses = _cash_expenses(db, day)
    cash_handovers = _handover_total(db, day, cash_only=True)
    session = get_session(db, day)
    opening = money(session.opening_cash) if session else ZERO
    expected = money(opening + cash_in - cash_refunds - cash_expenses - cash_handovers)
    counted = money(session.counted_cash) if session and session.counted_cash is not None else None
    difference = money(counted - expected) if counted is not None else None

    start, end = day_bounds_utc(day)
    handovers = list(
        db.scalars(
            select(CashHandover)
            .where(CashHandover.handed_at >= start, CashHandover.handed_at <= end)
            .order_by(CashHandover.handed_at.desc(), CashHandover.id.desc())
        )
    )

    order = {method: index for index, method in enumerate(allowed_methods(db))}
    methods = []
    for method in set(by_method) | set(order):
        bucket = by_method.get(method, {"in": ZERO, "out": ZERO})
        inflow = money(bucket["in"])
        outflow = money(bucket["out"])
        methods.append(
            {
                "method": method,
                "inflow": inflow,
                "outflow": outflow,
                "net": money(inflow - outflow),
            }
        )
    methods.sort(key=lambda row: (order.get(row["method"], 999), row["method"]))

    return {
        "session_date": day,
        "opening_cash": opening,
        "cash_in": cash_in,
        "upi_in": upi_in,
        "other_in": other_in,
        "cash_refunds": cash_refunds,
        "cash_expenses": cash_expenses,
        "cash_handovers": cash_handovers,
        "expected_closing_cash": expected,
        "counted_cash": counted,
        "difference": difference,
        "total_collected": total_in,
        "total_refunds": total_out,
        "net_collected": money(total_in - total_out),
        "pending_balances": pending_balances(db),
        "methods": methods,
        "handovers": handovers,
        "session": session,
        "payment_count": payment_count,
    }


def upsert_session(db: Session, day: date, payload: CashSessionUpsert) -> CashSession:
    session = get_session(db, day)
    if session:
        if payload.version is None:
            raise ConflictError(
                "A cash session already exists for this date. Reload and try again.",
                code="version_required",
            )
        if session.version != payload.version:
            raise ConflictError(
                "This cash session was changed elsewhere. Reload it and try again.",
                code="version_conflict",
            )
        before = snapshot(session, ["opening_cash", "counted_cash", "notes", "version"])
        session.opening_cash = money(payload.opening_cash)
        session.counted_cash = money(payload.counted_cash) if payload.counted_cash is not None else None
        session.notes = payload.notes
        session.version += 1
        audit(
            db,
            entity_type="cash_session",
            entity_id=session.id,
            action="updated",
            before=before,
            after=snapshot(session, ["opening_cash", "counted_cash", "notes", "version"]),
        )
    else:
        session = CashSession(
            session_date=day,
            opening_cash=money(payload.opening_cash),
            counted_cash=money(payload.counted_cash) if payload.counted_cash is not None else None,
            notes=payload.notes,
            version=1,
        )
        db.add(session)
        db.flush()
        audit(
            db,
            entity_type="cash_session",
            entity_id=session.id,
            action="created",
            after=snapshot(session, ["session_date", "opening_cash", "counted_cash", "notes", "version"]),
        )
    db.commit()
    return session


def list_sessions(db: Session, *, date_from: date | None = None, date_to: date | None = None) -> list[CashSession]:
    stmt = select(CashSession)
    if date_from:
        stmt = stmt.where(CashSession.session_date >= date_from)
    if date_to:
        stmt = stmt.where(CashSession.session_date <= date_to)
    return list(db.scalars(stmt.order_by(CashSession.session_date.desc())))


def create_handover(db: Session, payload: CashHandoverCreate) -> tuple[CashHandover, bool]:
    if payload.idempotency_key:
        existing = db.scalar(select(CashHandover).where(CashHandover.idempotency_key == payload.idempotency_key))
        if existing:
            return existing, False
    method = validate_method(db, payload.method)
    handover = CashHandover(
        idempotency_key=payload.idempotency_key,
        handed_at=payload.handed_at or utcnow(),
        amount=money(payload.amount),
        method=method,
        recipient=payload.recipient,
        reference=payload.reference,
        notes=payload.notes,
    )
    db.add(handover)
    db.flush()
    audit(
        db,
        entity_type="cash_handover",
        entity_id=handover.id,
        action="created",
        after=snapshot(handover, ["handed_at", "amount", "method", "recipient", "reference", "notes"]),
        note="Cash custody transfer (not an expense)",
    )
    db.commit()
    return handover, True


def list_handovers(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    method: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CashHandover], int]:
    conditions = []
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(CashHandover.handed_at >= start)
    if end:
        conditions.append(CashHandover.handed_at <= end)
    if method:
        conditions.append(CashHandover.method == method)
    stmt = select(CashHandover)
    count_stmt = select(func.count(CashHandover.id))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(
            stmt.order_by(CashHandover.handed_at.desc(), CashHandover.id.desc()).limit(limit).offset(offset)
        )
    )
    return items, total


def add_adjustment(db: Session, payload: AdjustmentCreate) -> tuple[Payment, bool]:
    if payload.idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == payload.idempotency_key))
        if existing:
            return existing, False
    method = validate_method(db, payload.method)
    if not (payload.notes or payload.reference):
        raise ValidationError("A note or reference is required to explain a cash adjustment")
    payment = Payment(
        idempotency_key=payload.idempotency_key,
        sale_id=None,
        amount=money(payload.amount),
        direction=PaymentDirection.inflow if payload.direction == "in" else PaymentDirection.outflow,
        kind=PaymentKind.adjustment,
        method=method,
        paid_at=payload.occurred_at or payload.paid_at or utcnow(),
        reference=payload.reference,
        notes=payload.notes,
    )
    db.add(payment)
    db.flush()
    audit(
        db,
        entity_type="payment",
        entity_id=payment.id,
        action="adjustment_created",
        after=snapshot(payment, ["amount", "direction", "method", "paid_at", "reference", "notes"]),
    )
    db.commit()
    return payment, True


def list_payments(
    db: Session,
    *,
    sale_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    method: str | None = None,
    direction: PaymentDirection | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Payment], int]:
    conditions = []
    if sale_id:
        conditions.append(Payment.sale_id == sale_id)
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(Payment.paid_at >= start)
    if end:
        conditions.append(Payment.paid_at <= end)
    if method:
        conditions.append(Payment.method == method)
    if direction:
        conditions.append(Payment.direction == direction)
    stmt = select(Payment)
    count_stmt = select(func.count(Payment.id))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(stmt.order_by(Payment.paid_at.desc(), Payment.id.desc()).limit(limit).offset(offset))
    )
    return items, total
