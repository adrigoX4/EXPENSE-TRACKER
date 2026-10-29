from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Customer,
    Delivery,
    DeliveryStatus,
    MovementType,
    Payment,
    PaymentDirection,
    PaymentKind,
    PaymentStatus,
    Product,
    ReconciliationRecord,
    ReconciliationStatus,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    SaleSource,
    SaleStatus,
    StockMovement,
)
from app.schemas import SaleCreate, SaleReturnCreate, SaleUpdate, SaleVoidIn
from app.serializers import sale_detail_out, sale_out
from app.services.settings_service import validate_method
from app.services.sync_service import record_sync
from app.utils import money, range_bounds_utc, utcnow

SALE_FIELDS = [
    "source",
    "external_order_id",
    "occurred_at",
    "subtotal",
    "discount",
    "total",
    "returned_value",
    "amount_paid",
    "refunded_amount",
    "payment_status",
    "status",
    "customer_ref",
    "notes",
    "reconciliation_status",
    "version",
]


def _sale_load_options():
    return (
        selectinload(Sale.items),
        selectinload(Sale.payments),
        selectinload(Sale.returns).selectinload(SaleReturn.items).selectinload(SaleReturnItem.sale_item),
        selectinload(Sale.delivery),
        selectinload(Sale.customer),
        selectinload(Sale.reconciliation_records),
    )


def get_sale(db: Session, sale_id: int) -> Sale:
    sale = db.scalar(select(Sale).options(*_sale_load_options()).where(Sale.id == sale_id))
    if not sale:
        raise NotFoundError("Sale not found")
    return sale


def find_sale_by_idempotency(db: Session, key: str) -> Sale | None:
    return db.scalar(
        select(Sale).options(*_sale_load_options()).where(Sale.idempotency_key == key)
    )


def find_sale_by_uuid(db: Session, client_uuid: str) -> Sale | None:
    return db.scalar(select(Sale).options(*_sale_load_options()).where(Sale.uuid == client_uuid))


def find_sale_by_external_id(db: Session, external_order_id: str) -> Sale | None:
    return db.scalar(select(Sale).where(func.lower(Sale.external_order_id) == external_order_id.lower()))


def external_conflict_details(sale: Sale) -> dict:
    return {
        "sale_id": sale.id,
        "uuid": sale.uuid,
        "source": sale.source.value,
        "occurred_at": sale.occurred_at.isoformat(),
        "total": str(sale.total),
        "customer": sale.customer.name if sale.customer else sale.customer_ref,
    }


def recalc_sale(sale: Sale) -> None:
    amount_paid = money(sum((p.amount for p in sale.payments if p.direction == PaymentDirection.inflow), Decimal("0")))
    refunded = money(sum((p.amount for p in sale.payments if p.direction == PaymentDirection.outflow), Decimal("0")))
    returned_value = money(sum((r.returned_value for r in sale.returns), Decimal("0")))
    sale.amount_paid = amount_paid
    sale.refunded_amount = refunded
    sale.returned_value = returned_value

    if sale.status == SaleStatus.voided:
        sale.payment_status = PaymentStatus.voided
        return

    due = sale.total - returned_value - (amount_paid - refunded)
    if due <= Decimal("0.01") and (amount_paid > 0 or sale.total == 0):
        sale.payment_status = PaymentStatus.paid
    elif amount_paid - refunded > 0:
        sale.payment_status = PaymentStatus.partial
    else:
        sale.payment_status = PaymentStatus.unpaid


def create_sale(db: Session, payload: SaleCreate, *, header_idempotency_key: str | None = None) -> tuple[Sale, bool]:
    key = header_idempotency_key or payload.idempotency_key
    if key:
        existing = find_sale_by_idempotency(db, key)
        if existing:
            record_sync(
                db,
                operation_id=key,
                entity_type="sale",
                entity_id=existing.id,
                operation_type="create",
                local_created_at=payload.occurred_at,
            )
            db.commit()
            return existing, False
    if payload.client_uuid:
        existing = find_sale_by_uuid(db, payload.client_uuid)
        if existing:
            if key:
                record_sync(
                    db,
                    operation_id=key,
                    entity_type="sale",
                    entity_id=existing.id,
                    operation_type="create",
                    local_created_at=payload.occurred_at,
                )
                db.commit()
            return existing, False

    if payload.external_order_id:
        existing = find_sale_by_external_id(db, payload.external_order_id)
        if existing:
            raise ConflictError(
                f"Website order '{payload.external_order_id}' is already recorded as sale #{existing.id}. "
                "Review it in Reconciliation instead of recording it again.",
                code="duplicate_external_order_id",
                details={"existing_sale": external_conflict_details(existing)},
            )

    occurred_at = payload.occurred_at or utcnow()
    products: list[Product] = []
    computed_lines: list[dict] = []
    subtotal = Decimal("0.00")
    negative_stock: list[dict] = []

    for item in payload.items:
        product = db.get(Product, item.product_id)
        if not product:
            raise ValidationError(f"Product #{item.product_id} does not exist", details={"product_id": item.product_id})
        if not product.is_active:
            raise ConflictError(
                f"'{product.name}' is inactive and cannot be sold.",
                code="product_inactive",
                details={"product_id": product.id, "product_name": product.name},
            )
        unit_price = money(item.unit_price) if item.unit_price is not None else money(product.selling_price)
        line_discount = money(item.line_discount)
        gross = money(unit_price * item.quantity)
        if line_discount > gross:
            raise ValidationError(f"Line discount for '{product.name}' exceeds the line value")
        line_total = money(gross - line_discount)
        cost_total = money(money(product.purchase_cost) * item.quantity)
        subtotal += line_total
        if product.stock_quantity - item.quantity < 0:
            negative_stock.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "available": product.stock_quantity,
                    "requested": item.quantity,
                }
            )
        products.append(product)
        computed_lines.append(
            {
                "product": product,
                "quantity": item.quantity,
                "unit_price": unit_price,
                "unit_cost": money(product.purchase_cost),
                "line_discount": line_discount,
                "line_total": line_total,
                "cost_total": cost_total,
            }
        )

    subtotal = money(subtotal)
    discount = money(payload.discount)
    if discount > subtotal:
        raise ValidationError("Discount cannot be greater than the sale subtotal")
    total = money(subtotal - discount)

    if negative_stock and not payload.allow_negative_stock:
        raise ConflictError(
            "This sale would make stock negative for: "
            + ", ".join(f"{row['product_name']} ({row['available']} available)" for row in negative_stock)
            + ". Confirm to continue if this is intentional.",
            code="negative_stock",
            details={"items": negative_stock},
        )
    negative_reason = None
    if negative_stock and payload.allow_negative_stock:
        negative_reason = (payload.negative_stock_reason or "").strip()
        if len(negative_reason) < 2:
            raise ValidationError(
                "A reason is required when recording a sale that makes stock negative.",
                details={"items": negative_stock},
            )
    negative_note = f" · negative stock reason: {negative_reason}" if negative_reason else ""

    customer: Customer | None = None
    if payload.customer_id:
        customer = db.get(Customer, payload.customer_id)
        if not customer:
            raise ValidationError("Selected customer does not exist")
    elif payload.customer_name:
        customer = Customer(
            name=payload.customer_name,
            phone=payload.customer_phone,
            room_ref=payload.customer_room_ref,
        )
        db.add(customer)
        db.flush()

    sale = Sale(
        uuid=payload.client_uuid or None,
        idempotency_key=key,
        source=payload.source,
        external_order_id=payload.external_order_id,
        occurred_at=occurred_at,
        subtotal=subtotal,
        discount=discount,
        total=total,
        status=SaleStatus.completed,
        customer_id=customer.id if customer else None,
        customer_ref=payload.customer_ref or (customer.name if customer else None),
        notes=payload.notes,
        reconciliation_status=ReconciliationStatus.recorded,
        version=1,
    )
    if not sale.uuid:
        import uuid as _uuid

        sale.uuid = str(_uuid.uuid4())
    db.add(sale)
    db.flush()

    for line in computed_lines:
        product = line["product"]
        sale_item = SaleItem(
            sale=sale,
            product_id=product.id,
            product_name=product.name,
            sku=product.sku,
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            unit_cost=line["unit_cost"],
            line_discount=line["line_discount"],
            line_total=line["line_total"],
            cost_total=line["cost_total"],
        )
        db.add(sale_item)
        db.flush()

        old_stock = product.stock_quantity
        product.stock_quantity = old_stock - line["quantity"]
        db.add(
            StockMovement(
                product_id=product.id,
                movement_type=MovementType.sale,
                quantity_change=-line["quantity"],
                unit_cost=line["unit_cost"],
                occurred_at=occurred_at,
                reason=f"Sale {sale.uuid}{negative_note}",
                sale_id=sale.id,
                sale_item_id=sale_item.id,
            )
        )
        audit(
            db,
            entity_type="product",
            entity_id=product.id,
            action="stock_sold",
            before={"stock_quantity": old_stock},
            after={"stock_quantity": product.stock_quantity},
            note=f"Sale #{sale.id}",
        )

    if payload.delivery_status is not None:
        delivery = Delivery(
            sale_id=sale.id,
            status=payload.delivery_status,
            delivery_person=payload.delivery_person,
            notes=payload.delivery_notes,
        )
        if payload.delivery_status == DeliveryStatus.out_for_delivery:
            delivery.dispatched_at = occurred_at
        elif payload.delivery_status == DeliveryStatus.delivered:
            delivery.dispatched_at = occurred_at
            delivery.delivered_at = occurred_at
        db.add(delivery)
        db.flush()
        sale.delivery = delivery

    initial_payments = list(payload.initial_payments or [])
    if payload.initial_payment:
        initial_payments.insert(0, payload.initial_payment)
    if initial_payments:
        paid_total = money(sum((money(entry.amount) for entry in initial_payments), Decimal("0")))
        if paid_total > total + Decimal("0.01"):
            raise ValidationError("Payments received cannot exceed the sale total")
        for entry in initial_payments:
            method = validate_method(db, entry.method)
            amount = money(entry.amount)
            paid_at = entry.paid_at or occurred_at
            payment = Payment(
                sale=sale,
                amount=amount,
                direction=PaymentDirection.inflow,
                kind=PaymentKind.sale_payment,
                method=method,
                paid_at=paid_at,
                reference=entry.reference,
                notes=entry.notes,
            )
            db.add(payment)
        db.flush()

    if sale.source != SaleSource.manual or sale.external_order_id:
        db.add(
            ReconciliationRecord(
                sale_id=sale.id,
                external_order_id=sale.external_order_id,
                status=ReconciliationStatus.recorded,
                notes="Sale recorded in the personal app",
            )
        )

    recalc_sale(sale)
    sale.version = 1
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="created",
        after=snapshot(sale, SALE_FIELDS),
        note=f"Source: {sale.source.value}{negative_note}",
    )
    if key:
        record_sync(
            db,
            operation_id=key,
            entity_type="sale",
            entity_id=sale.id,
            operation_type="create",
            local_created_at=occurred_at,
        )
    db.commit()
    return get_sale(db, sale.id), True


def list_sales(
    db: Session,
    *,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    source: SaleSource | None = None,
    status: SaleStatus | None = None,
    payment_status: PaymentStatus | None = None,
    delivery_status: str | None = None,
    reconciliation_status: ReconciliationStatus | None = None,
    product_id: int | None = None,
    has_external_id: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Sale], int, dict]:
    conditions = []
    if search:
        term = f"%{search.strip().lower()}%"
        matching_products = select(SaleItem.sale_id).where(
            or_(
                func.lower(SaleItem.product_name).like(term),
                func.lower(func.coalesce(SaleItem.sku, "")).like(term),
            )
        )
        conditions.append(
            or_(
                func.lower(func.coalesce(Sale.external_order_id, "")).like(term),
                func.lower(Sale.uuid).like(term),
                func.lower(func.coalesce(Sale.customer_ref, "")).like(term),
                func.lower(func.coalesce(Customer.name, "")).like(term),
                func.lower(func.coalesce(Sale.notes, "")).like(term),
                Sale.id.in_(matching_products),
            )
        )
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(Sale.occurred_at >= start)
    if end:
        conditions.append(Sale.occurred_at <= end)
    if source:
        conditions.append(Sale.source == source)
    if status:
        conditions.append(Sale.status == status)
    if payment_status:
        conditions.append(Sale.payment_status == payment_status)
    if reconciliation_status:
        conditions.append(Sale.reconciliation_status == reconciliation_status)
    if has_external_id is True:
        conditions.append(Sale.external_order_id.is_not(None))
    elif has_external_id is False:
        conditions.append(Sale.external_order_id.is_(None))

    stmt = select(Sale).outerjoin(Customer, Sale.customer_id == Customer.id)
    count_stmt = select(Sale.id).outerjoin(Customer, Sale.customer_id == Customer.id)
    if product_id:
        stmt = stmt.join(SaleItem, SaleItem.sale_id == Sale.id)
        count_stmt = count_stmt.join(SaleItem, SaleItem.sale_id == Sale.id)
        conditions.append(SaleItem.product_id == product_id)
    if delivery_status:
        stmt = stmt.outerjoin(Delivery, Delivery.sale_id == Sale.id)
        count_stmt = count_stmt.outerjoin(Delivery, Delivery.sale_id == Sale.id)
        if delivery_status == "none":
            conditions.append(Delivery.id.is_(None))
        else:
            conditions.append(Delivery.status == DeliveryStatus(delivery_status))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    ids_subquery = count_stmt.distinct().subquery()
    total = db.scalar(select(func.count()).select_from(ids_subquery)) or 0

    due = Sale.total - Sale.returned_value - (Sale.amount_paid - Sale.refunded_amount)
    aggregates_stmt = select(
        func.coalesce(
            func.sum(case((Sale.status == SaleStatus.completed, Sale.total - Sale.returned_value), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((Sale.status == SaleStatus.completed, Sale.amount_paid - Sale.refunded_amount), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (and_(Sale.status == SaleStatus.completed, due > 0), due),
                    else_=0,
                )
            ),
            0,
        ),
    ).where(Sale.id.in_(select(ids_subquery.c.id)))
    revenue, collected, outstanding = db.execute(aggregates_stmt).one()

    items = list(
        db.scalars(
            stmt.options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.customer),
                selectinload(Sale.delivery),
            )
            .order_by(Sale.occurred_at.desc(), Sale.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    aggregates = {
        "revenue": money(revenue),
        "collected": money(collected),
        "outstanding": money(outstanding),
    }
    return items, total, aggregates


def update_sale(db: Session, sale_id: int, payload: SaleUpdate) -> Sale:
    sale = get_sale(db, sale_id)
    if sale.version != payload.version:
        raise ConflictError(
            "This sale was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": sale_detail_out(sale)},
        )
    before = snapshot(sale, SALE_FIELDS)
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "external_order_id" in changes:
        new_external = changes["external_order_id"]
        if new_external:
            existing = find_sale_by_external_id(db, new_external)
            if existing and existing.id != sale.id:
                raise ConflictError(
                    f"Website order '{new_external}' is already linked to sale #{existing.id}.",
                    code="duplicate_external_order_id",
                    details={"existing_sale": external_conflict_details(existing)},
                )
    old_reconciliation = sale.reconciliation_status
    for field, value in changes.items():
        setattr(sale, field, value)

    if "reconciliation_status" in changes and sale.reconciliation_status != old_reconciliation:
        db.add(
            ReconciliationRecord(
                sale_id=sale.id,
                external_order_id=sale.external_order_id,
                status=sale.reconciliation_status,
                notes="Updated from sale record",
            )
        )
    sale.version += 1
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="updated",
        before=before,
        after=snapshot(sale, SALE_FIELDS),
    )
    db.flush()
    return get_sale(db, sale.id)


def add_payment(
    db: Session,
    sale_id: int,
    *,
    amount: Decimal,
    method: str,
    paid_at,
    reference: str | None,
    notes: str | None,
    idempotency_key: str | None = None,
) -> tuple[Sale, Payment, bool]:
    if idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing and existing.sale_id == sale_id:
            return get_sale(db, sale_id), existing, False

    sale = get_sale(db, sale_id)
    if sale.status == SaleStatus.voided:
        raise ConflictError("Cannot record a payment against a cancelled sale.", code="sale_voided")
    method = validate_method(db, method)
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero")
    payment = Payment(
        sale=sale,
        amount=amount,
        direction=PaymentDirection.inflow,
        kind=PaymentKind.sale_payment,
        method=method,
        paid_at=paid_at or utcnow(),
        reference=reference,
        notes=notes,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    db.flush()
    recalc_sale(sale)
    sale.version += 1
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="payment_recorded",
        after={"amount": str(amount), "method": method, "payment_id": payment.id},
    )
    if idempotency_key:
        record_sync(
            db,
            operation_id=idempotency_key,
            entity_type="payment",
            entity_id=payment.id,
            operation_type="create",
        )
    db.flush()
    return get_sale(db, sale.id), payment, True


def create_return(db: Session, sale_id: int, payload: SaleReturnCreate) -> tuple[Sale, SaleReturn, bool]:
    if payload.idempotency_key:
        existing_return = db.scalar(
            select(SaleReturn)
            .options(
                selectinload(SaleReturn.items).selectinload(SaleReturnItem.sale_item),
            )
            .where(SaleReturn.idempotency_key == payload.idempotency_key)
        )
        if existing_return:
            return get_sale(db, existing_return.sale_id), existing_return, False

    sale = get_sale(db, sale_id)
    if sale.status == SaleStatus.voided:
        raise ConflictError("Cannot return items from a cancelled sale.", code="sale_voided")

    item_map = {item.id: item for item in sale.items}
    returned_at = payload.returned_at or utcnow()
    requested: list[dict] = []
    returned_value = Decimal("0.00")
    cost_value = Decimal("0.00")
    for request in payload.items:
        sale_item = item_map.get(request.sale_item_id)
        if not sale_item:
            raise ValidationError(f"Sale item #{request.sale_item_id} does not belong to this sale")
        remaining = sale_item.quantity - sale_item.returned_quantity
        if request.quantity > remaining:
            raise ValidationError(
                f"Cannot return {request.quantity} of '{sale_item.product_name}'. Only {remaining} remain eligible.",
                details={
                    "sale_item_id": sale_item.id,
                    "remaining": remaining,
                    "requested": request.quantity,
                },
            )
        line_value = money(sale_item.line_total * Decimal(request.quantity) / Decimal(sale_item.quantity))
        line_cost = money(sale_item.cost_total * Decimal(request.quantity) / Decimal(sale_item.quantity))
        returned_value += line_value
        cost_value += line_cost
        requested.append(
            {
                "sale_item": sale_item,
                "quantity": request.quantity,
                "unit_price": sale_item.unit_price,
                "line_value": line_value,
                "cost_total": line_cost,
            }
        )
    returned_value = money(returned_value)
    cost_value = money(cost_value)

    refund_amount = money(payload.refund_amount)
    if refund_amount > returned_value + Decimal("0.01"):
        raise ValidationError("Refund amount cannot exceed the returned item value")
    net_paid = sale.amount_paid - sale.refunded_amount
    if refund_amount > net_paid + Decimal("0.01"):
        raise ValidationError("Refund amount cannot exceed the amount collected for this sale")

    refund_method: str | None = None
    if refund_amount > 0:
        method = payload.refund_method
        if not method:
            last_in = next((p for p in reversed(sale.payments) if p.direction == PaymentDirection.inflow), None)
            method = last_in.method if last_in else "cash"
        refund_method = validate_method(db, method)

    sale_return = SaleReturn(
        sale=sale,
        idempotency_key=payload.idempotency_key,
        returned_at=returned_at,
        reason=payload.reason,
        restock=payload.restock,
        refund_amount=refund_amount,
        refund_method=refund_method,
        notes=payload.notes,
        returned_value=returned_value,
        cost_value=cost_value,
    )
    db.add(sale_return)
    db.flush()

    for row in requested:
        sale_item: SaleItem = row["sale_item"]
        return_item = SaleReturnItem(
            return_=sale_return,
            sale_item_id=sale_item.id,
            quantity=row["quantity"],
            unit_price=row["unit_price"],
            line_value=row["line_value"],
            cost_total=row["cost_total"],
        )
        db.add(return_item)
        db.flush()
        sale_item.returned_quantity += row["quantity"]

        if payload.restock:
            product = db.get(Product, sale_item.product_id)
            if product:
                old_stock = product.stock_quantity
                product.stock_quantity += row["quantity"]
                db.add(
                    StockMovement(
                        product_id=product.id,
                        movement_type=MovementType.return_,
                        quantity_change=row["quantity"],
                        unit_cost=sale_item.unit_cost,
                        occurred_at=returned_at,
                        reason=f"Return: {payload.reason}",
                        sale_id=sale.id,
                        sale_item_id=sale_item.id,
                        sale_return_id=sale_return.id,
                        sale_return_item_id=return_item.id,
                    )
                )
                audit(
                    db,
                    entity_type="product",
                    entity_id=product.id,
                    action="stock_returned",
                    before={"stock_quantity": old_stock},
                    after={"stock_quantity": product.stock_quantity},
                    note=f"Return #{sale_return.id}",
                )

    if refund_amount > 0:
        refund_key = (
            f"{payload.idempotency_key}:refund" if payload.idempotency_key else f"return:{sale_return.uuid}:refund"
        )
        refund = Payment(
            sale=sale,
            amount=refund_amount,
            direction=PaymentDirection.outflow,
            kind=PaymentKind.refund,
            method=refund_method or "cash",
            paid_at=returned_at,
            reference=f"Return {sale_return.uuid}",
            notes=payload.reason,
            idempotency_key=refund_key[:120],
        )
        db.add(refund)
        db.flush()

    recalc_sale(sale)
    sale.version += 1
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="return_recorded",
        after={
            "return_id": sale_return.id,
            "returned_value": str(returned_value),
            "refund_amount": str(refund_amount),
            "restock": payload.restock,
        },
        note=payload.reason,
    )
    if payload.idempotency_key:
        record_sync(
            db,
            operation_id=payload.idempotency_key,
            entity_type="sale_return",
            entity_id=sale_return.id,
            operation_type="create",
        )
    db.flush()
    return get_sale(db, sale.id), sale_return, True


def void_sale(db: Session, sale_id: int, payload: SaleVoidIn) -> Sale:
    sale = get_sale(db, sale_id)
    if sale.status == SaleStatus.voided:
        raise ConflictError("This sale is already cancelled.", code="already_voided")
    if payload.version is not None and sale.version != payload.version:
        raise ConflictError(
            "This sale was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": sale_detail_out(sale)},
        )
    if sale.returns:
        raise ConflictError(
            "This sale already has accepted returns. Record an additional return instead of cancelling the sale.",
            code="has_returns",
        )

    before = snapshot(sale, SALE_FIELDS)
    now = utcnow()
    if payload.restock:
        for item in sale.items:
            product = db.get(Product, item.product_id)
            if not product:
                continue
            old_stock = product.stock_quantity
            product.stock_quantity += item.quantity
            db.add(
                StockMovement(
                    product_id=product.id,
                    movement_type=MovementType.return_,
                    quantity_change=item.quantity,
                    unit_cost=item.unit_cost,
                    occurred_at=now,
                    reason=f"Sale cancelled: {payload.reason}",
                    sale_id=sale.id,
                    sale_item_id=item.id,
                )
            )
            audit(
                db,
                entity_type="product",
                entity_id=product.id,
                action="stock_restored_after_void",
                before={"stock_quantity": old_stock},
                after={"stock_quantity": product.stock_quantity},
                note=f"Cancelled sale #{sale.id}",
            )

    net_paid = sale.amount_paid - sale.refunded_amount
    if payload.refund_paid and net_paid > 0:
        method = payload.refund_method
        if not method:
            last_in = next((p for p in reversed(sale.payments) if p.direction == PaymentDirection.inflow), None)
            method = last_in.method if last_in else "cash"
        method = validate_method(db, method)
        refund = Payment(
            sale=sale,
            amount=net_paid,
            direction=PaymentDirection.outflow,
            kind=PaymentKind.refund,
            method=method,
            paid_at=now,
            reference=f"Void {sale.uuid}",
            notes=payload.reason,
        )
        db.add(refund)
        db.flush()

    sale.status = SaleStatus.voided
    sale.void_reason = payload.reason
    sale.voided_at = now
    sale.version += 1
    recalc_sale(sale)
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="voided",
        before=before,
        after=snapshot(sale, SALE_FIELDS),
        note=payload.reason,
    )
    db.flush()
    return get_sale(db, sale.id)


def external_reconciliation_status(db: Session, sale: Sale, status: ReconciliationStatus, notes: str | None) -> Sale:
    old = sale.reconciliation_status
    sale.reconciliation_status = status
    sale.version += 1
    db.add(
        ReconciliationRecord(
            sale_id=sale.id,
            external_order_id=sale.external_order_id,
            status=status,
            notes=notes,
            reviewed_at=utcnow(),
        )
    )
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="reconciliation_updated",
        before={"reconciliation_status": old.value},
        after={"reconciliation_status": status.value},
        note=notes,
    )
    db.flush()
    return sale
