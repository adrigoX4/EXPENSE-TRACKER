from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Expense,
    MovementType,
    Product,
    StockMovement,
    StockReceipt,
    StockReceiptItem,
)
from app.schemas import MovementCreate, StockReceiptCreate
from app.services.products import get_product, product_out
from app.services.settings_service import (
    inventory_category,
    validate_expense_category,
    validate_method,
)
from app.utils import money, range_bounds_utc, utcnow


def _idempotent_receipt(db: Session, key: str | None) -> StockReceipt | None:
    if not key:
        return None
    return db.scalar(
        select(StockReceipt)
        .options(selectinload(StockReceipt.items).selectinload(StockReceiptItem.product))
        .where(StockReceipt.idempotency_key == key)
    )


def create_receipt(db: Session, payload: StockReceiptCreate) -> tuple[StockReceipt, bool]:
    existing = _idempotent_receipt(db, payload.idempotency_key)
    if existing:
        return existing, False

    method = validate_method(db, payload.payment_method)
    received_at = payload.received_at or utcnow()
    products: list[Product] = []
    total = Decimal("0.00")
    for item in payload.items:
        product = get_product(db, item.product_id)
        if not product.is_active:
            raise ConflictError(f"'{product.name}' is inactive and cannot be restocked.", code="product_inactive")
        products.append(product)
        total += money(item.unit_cost) * item.quantity
    total = money(total)

    receipt = StockReceipt(
        received_at=received_at,
        supplier_ref=payload.supplier_ref,
        total_cost=total,
        payment_method=method,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
    )
    db.add(receipt)
    db.flush()

    for item, product in zip(payload.items, products):
        unit_cost = money(item.unit_cost)
        line_total = money(unit_cost * item.quantity)
        receipt_item = StockReceiptItem(
            receipt_id=receipt.id,
            product_id=product.id,
            quantity=item.quantity,
            unit_cost=unit_cost,
            line_total=line_total,
        )
        db.add(receipt_item)
        db.flush()

        old_stock = product.stock_quantity
        old_cost = product.purchase_cost
        if old_stock > 0:
            product.purchase_cost = money(
                (Decimal(old_stock) * old_cost + Decimal(item.quantity) * unit_cost)
                / Decimal(old_stock + item.quantity)
            )
        else:
            product.purchase_cost = unit_cost
        product.stock_quantity = old_stock + item.quantity

        db.add(
            StockMovement(
                product_id=product.id,
                movement_type=MovementType.receipt,
                quantity_change=item.quantity,
                unit_cost=unit_cost,
                occurred_at=received_at,
                reason=f"Stock received{f' from {payload.supplier_ref}' if payload.supplier_ref else ''}",
                stock_receipt_id=receipt.id,
                stock_receipt_item_id=receipt_item.id,
                notes=payload.notes,
            )
        )
        audit(
            db,
            entity_type="product",
            entity_id=product.id,
            action="stock_received",
            before={"stock_quantity": old_stock, "purchase_cost": old_cost},
            after={"stock_quantity": product.stock_quantity, "purchase_cost": product.purchase_cost},
            note=f"Receipt #{receipt.id}",
        )

    if total > 0:
        category = validate_expense_category(db, inventory_category(db))
        expense = Expense(
            occurred_at=received_at,
            category=category,
            description=f"Stock purchase{' - ' + payload.supplier_ref if payload.supplier_ref else f' (receipt #{receipt.id})'}",
            amount=total,
            method=method,
            paid_to=payload.supplier_ref,
            reference=f"Receipt #{receipt.id}",
            notes=payload.notes,
        )
        db.add(expense)
        db.flush()
        receipt.expense_id = expense.id
        audit(
            db,
            entity_type="expense",
            entity_id=expense.id,
            action="created",
            after=snapshot(expense, ["occurred_at", "category", "description", "amount", "method", "reference"]),
            note=f"Linked to stock receipt #{receipt.id}",
        )

    receipt = db.scalar(
        select(StockReceipt)
        .options(selectinload(StockReceipt.items).selectinload(StockReceiptItem.product))
        .where(StockReceipt.id == receipt.id)
    )
    db.flush()
    return receipt, True


def list_receipts(db: Session, *, limit: int = 50, offset: int = 0) -> tuple[list[StockReceipt], int]:
    total = db.scalar(select(func.count(StockReceipt.id))) or 0
    items = list(
        db.scalars(
            select(StockReceipt)
            .options(selectinload(StockReceipt.items).selectinload(StockReceiptItem.product))
            .order_by(StockReceipt.received_at.desc(), StockReceipt.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def create_manual_movement(db: Session, payload: MovementCreate) -> tuple[StockMovement, bool]:
    if payload.idempotency_key:
        existing = db.scalar(
            select(StockMovement).where(StockMovement.idempotency_key == payload.idempotency_key)
        )
        if existing:
            return existing, False

    product = get_product(db, payload.product_id)
    movement_type = MovementType(payload.movement_type)
    new_stock = product.stock_quantity + payload.quantity_change
    if new_stock < 0 and not payload.allow_negative_stock:
        raise ConflictError(
            f"This movement would leave '{product.name}' at {new_stock} units. "
            "Confirm negative stock if this is intentional.",
            code="negative_stock",
            details={"product_id": product.id, "product_name": product.name, "resulting_stock": new_stock},
        )

    old_stock = product.stock_quantity
    old_cost = product.purchase_cost
    product.stock_quantity = new_stock
    if payload.unit_cost is not None:
        product.purchase_cost = money(payload.unit_cost)

    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_change=payload.quantity_change,
        unit_cost=money(payload.unit_cost) if payload.unit_cost is not None else None,
        occurred_at=payload.occurred_at or utcnow(),
        reason=payload.reason,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
    )
    db.add(movement)
    audit(
        db,
        entity_type="product",
        entity_id=product.id,
        action=f"stock_{payload.movement_type}",
        before={"stock_quantity": old_stock, "purchase_cost": old_cost},
        after={"stock_quantity": product.stock_quantity, "purchase_cost": product.purchase_cost},
        note=payload.reason,
    )
    db.flush()
    return movement, True


def list_movements(
    db: Session,
    *,
    product_id: int | None = None,
    movement_type: MovementType | None = None,
    date_from=None,
    date_to=None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[StockMovement], int]:
    conditions = []
    if product_id:
        conditions.append(StockMovement.product_id == product_id)
    if movement_type:
        conditions.append(StockMovement.movement_type == movement_type)
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(StockMovement.occurred_at >= start)
    if end:
        conditions.append(StockMovement.occurred_at <= end)
    if search:
        term = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Product.name).like(term),
                func.lower(StockMovement.reason).like(term),
                func.lower(func.coalesce(StockMovement.notes, "")).like(term),
            )
        )

    stmt = select(StockMovement).join(Product, StockMovement.product_id == Product.id)
    count_stmt = select(func.count(StockMovement.id)).join(Product, StockMovement.product_id == Product.id)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(
            stmt.options(selectinload(StockMovement.product))
            .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total
