from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError
from app.models import Delivery, DeliveryStatus, Sale
from app.schemas import DeliveryCreate, DeliveryUpdate
from app.utils import range_bounds_utc, utcnow

DELIVERY_FIELDS = ["status", "delivery_person", "notes", "dispatched_at", "delivered_at", "version"]


def _options():
    return (
        selectinload(Delivery.sale).selectinload(Sale.customer),
        selectinload(Delivery.sale).selectinload(Sale.items),
    )


def get_delivery(db: Session, delivery_id: int) -> Delivery:
    delivery = db.scalar(select(Delivery).options(*_options()).where(Delivery.id == delivery_id))
    if not delivery:
        raise NotFoundError("Delivery not found")
    return delivery


def get_delivery_for_sale(db: Session, sale_id: int) -> Delivery | None:
    return db.scalar(select(Delivery).options(*_options()).where(Delivery.sale_id == sale_id))


def list_deliveries(
    db: Session,
    *,
    status: DeliveryStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Delivery], int, dict[str, int]]:
    base_conditions = []
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        base_conditions.append(Sale.occurred_at >= start)
    if end:
        base_conditions.append(Sale.occurred_at <= end)

    stmt = select(Delivery).join(Sale, Delivery.sale_id == Sale.id).outerjoin(Sale.customer)
    count_stmt = select(Delivery.id).join(Sale, Delivery.sale_id == Sale.id).outerjoin(Sale.customer)
    conditions = list(base_conditions)
    if search:
        term = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(func.coalesce(Sale.customer_ref, "")).like(term),
                func.lower(func.coalesce(Sale.external_order_id, "")).like(term),
                func.lower(Sale.uuid).like(term),
                func.lower(func.coalesce(Delivery.delivery_person, "")).like(term),
                func.lower(func.coalesce(Delivery.notes, "")).like(term),
            )
        )
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    if status:
        stmt = stmt.where(Delivery.status == status)
        count_stmt = count_stmt.where(Delivery.status == status)

    total = db.scalar(select(func.count()).select_from(count_stmt.distinct().subquery())) or 0
    items = list(
        db.scalars(
            stmt.options(*_options())
            .order_by(Sale.occurred_at.desc(), Delivery.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )

    counts = {state.value: 0 for state in DeliveryStatus}
    count_rows = db.execute(
        select(Delivery.status, func.count(Delivery.id))
        .join(Sale, Delivery.sale_id == Sale.id)
        .outerjoin(Sale.customer)
        .where(*base_conditions)
        .group_by(Delivery.status)
    ).all()
    for state, count in count_rows:
        counts[state.value if hasattr(state, "value") else str(state)] = count
    return items, total, counts


def create_delivery(db: Session, payload: DeliveryCreate) -> tuple[Delivery, bool]:
    sale = db.get(Sale, payload.sale_id)
    if not sale:
        raise NotFoundError("Sale not found")
    existing = get_delivery_for_sale(db, sale.id)
    if existing:
        return existing, False
    now = utcnow()
    delivery = Delivery(
        sale_id=sale.id,
        status=payload.status,
        delivery_person=payload.delivery_person,
        notes=payload.notes,
        dispatched_at=now if payload.status == DeliveryStatus.out_for_delivery else None,
        delivered_at=now if payload.status == DeliveryStatus.delivered else None,
        version=1,
    )
    db.add(delivery)
    db.flush()
    audit(
        db,
        entity_type="delivery",
        entity_id=delivery.id,
        action="created",
        after=snapshot(delivery, DELIVERY_FIELDS),
        note=f"Sale #{sale.id}",
    )
    db.commit()
    return get_delivery(db, delivery.id), True


def update_delivery(db: Session, delivery_id: int, payload: DeliveryUpdate) -> Delivery:
    delivery = get_delivery(db, delivery_id)
    if payload.version is not None and delivery.version != payload.version:
        raise ConflictError(
            "This delivery was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": snapshot(delivery, DELIVERY_FIELDS)},
        )
    before = snapshot(delivery, DELIVERY_FIELDS)
    delivery.status = payload.status
    if payload.delivery_person is not None:
        delivery.delivery_person = payload.delivery_person
    if payload.notes is not None:
        delivery.notes = payload.notes
    now = utcnow()
    if delivery.status == DeliveryStatus.out_for_delivery and delivery.dispatched_at is None:
        delivery.dispatched_at = now
    if delivery.status == DeliveryStatus.delivered:
        if delivery.dispatched_at is None:
            delivery.dispatched_at = now
        if delivery.delivered_at is None:
            delivery.delivered_at = now
    delivery.version += 1
    audit(
        db,
        entity_type="delivery",
        entity_id=delivery.id,
        action="updated",
        before=before,
        after=snapshot(delivery, DELIVERY_FIELDS),
    )
    db.commit()
    return get_delivery(db, delivery.id)
