from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    Delivery,
    DuplicateReview,
    DuplicateReviewStatus,
    ReconciliationRecord,
    ReconciliationStatus,
    Sale,
    SaleSource,
    SaleStatus,
)
from app.schemas import DuplicateReviewIn, ReconciliationLink, ReconciliationUpdate
from app.serializers import sale_out
from app.services.sales import external_reconciliation_status, find_sale_by_external_id, get_sale
from app.utils import local_day, range_bounds_utc, utcnow


def update_reconciliation(db: Session, sale_id: int, payload: ReconciliationUpdate) -> Sale:
    sale = get_sale(db, sale_id)
    if payload.version is not None and sale.version != payload.version:
        raise ConflictError(
            "This sale was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"sale_id": sale.id, "version": sale.version},
        )
    old_status = sale.reconciliation_status
    sale.reconciliation_status = payload.status
    sale.version += 1
    db.add(
        ReconciliationRecord(
            sale_id=sale.id,
            external_order_id=sale.external_order_id,
            status=payload.status,
            notes=payload.notes,
            website_total=payload.website_total,
            reviewed_at=utcnow(),
        )
    )
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="reconciliation_updated",
        before={"reconciliation_status": old_status.value},
        after={"reconciliation_status": payload.status.value},
        note=payload.notes,
    )
    db.commit()
    return get_sale(db, sale.id)


def link_external(db: Session, payload: ReconciliationLink) -> Sale:
    sale = get_sale(db, payload.sale_id)
    if payload.version is not None and sale.version != payload.version:
        raise ConflictError(
            "This sale was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"sale_id": sale.id, "version": sale.version},
        )
    existing = find_sale_by_external_id(db, payload.external_order_id)
    if existing and existing.id != sale.id:
        raise ConflictError(
            f"Website order '{payload.external_order_id}' is already linked to sale #{existing.id}.",
            code="duplicate_external_order_id",
            details={"sale_id": existing.id},
        )
    sale.external_order_id = payload.external_order_id
    sale.reconciliation_status = ReconciliationStatus.verified
    sale.version += 1
    db.add(
        ReconciliationRecord(
            sale_id=sale.id,
            external_order_id=sale.external_order_id,
            status=ReconciliationStatus.verified,
            notes=payload.notes or "Linked to website order after manual review",
            reviewed_at=utcnow(),
        )
    )
    audit(
        db,
        entity_type="sale",
        entity_id=sale.id,
        action="reconciliation_linked",
        after={"external_order_id": payload.external_order_id, "reconciliation_status": "verified"},
        note=payload.notes,
    )
    db.commit()
    return get_sale(db, sale.id)


def list_records(db: Session, *, sale_id: int | None = None, limit: int = 100) -> list[ReconciliationRecord]:
    stmt = select(ReconciliationRecord)
    if sale_id:
        stmt = stmt.where(ReconciliationRecord.sale_id == sale_id)
    return list(db.scalars(stmt.order_by(ReconciliationRecord.created_at.desc()).limit(limit)))


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _item_signature(sale: Sale) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((item.product_id, item.quantity) for item in sale.items))


def find_duplicate_candidates(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
) -> tuple[list[dict], list[dict]]:
    if not date_to:
        date_to = local_day(utcnow())
    if not date_from:
        date_from = date_to - timedelta(days=29)
    start, end = range_bounds_utc(date_from, date_to)

    sales = list(
        db.scalars(
            select(Sale)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.customer),
                selectinload(Sale.delivery),
            )
            .where(
                Sale.status == SaleStatus.completed,
                Sale.occurred_at >= start,
                Sale.occurred_at <= end,
            )
            .order_by(Sale.occurred_at)
        )
    )

    reviews = {
        _pair_key(review.sale_a_id, review.sale_b_id): review
        for review in db.scalars(select(DuplicateReview))
    }

    groups: dict[tuple[date, Decimal], list[Sale]] = {}
    for sale in sales:
        if sale.total <= 0:
            continue
        groups.setdefault((local_day(sale.occurred_at), sale.total), []).append(sale)

    candidates: list[dict] = []
    for (_, _total), group in groups.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                key = _pair_key(a.id, b.id)
                if key in reviews:
                    continue
                if a.external_order_id and b.external_order_id:
                    continue
                if (
                    a.reconciliation_status == ReconciliationStatus.verified
                    and b.reconciliation_status == ReconciliationStatus.verified
                ):
                    continue

                reasons = ["Same total", "Same business day"]
                score = 50
                customer_a = (a.customer.name if a.customer else a.customer_ref or "").strip().casefold()
                customer_b = (b.customer.name if b.customer else b.customer_ref or "").strip().casefold()
                if customer_a and customer_a == customer_b:
                    reasons.append("Same customer reference")
                    score += 15
                if _item_signature(a) == _item_signature(b) and _item_signature(a):
                    reasons.append("Identical product mix")
                    score += 15
                if a.source != b.source:
                    reasons.append("Different source")
                    score += 10
                if bool(a.external_order_id) != bool(b.external_order_id):
                    reasons.append("Only one has a website order ID")
                    score += 10
                candidates.append(
                    {
                        "sale_a": sale_out(a),
                        "sale_b": sale_out(b),
                        "score": score,
                        "reasons": reasons,
                        "review_status": None,
                    }
                )

    candidates.sort(key=lambda row: (-row["score"], row["sale_a"]["occurred_at"]))
    reviewed_pairs = [
        {
            "id": review.id,
            "sale_a_id": review.sale_a_id,
            "sale_b_id": review.sale_b_id,
            "status": review.status.value,
            "notes": review.notes,
            "resolved_at": review.resolved_at.isoformat() if review.resolved_at else None,
        }
        for review in reviews.values()
    ]
    return candidates[:limit], reviewed_pairs


def queue(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    status: ReconciliationStatus | None = None,
    limit: int = 200,
) -> dict:
    conditions = [Sale.status == SaleStatus.completed]
    start, end = range_bounds_utc(date_from, date_to)
    if start:
        conditions.append(Sale.occurred_at >= start)
    if end:
        conditions.append(Sale.occurred_at <= end)
    if status:
        conditions.append(Sale.reconciliation_status == status)

    items = list(
        db.scalars(
            select(Sale)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.customer),
                selectinload(Sale.delivery),
            )
            .where(*conditions)
            .order_by(Sale.occurred_at.desc(), Sale.id.desc())
            .limit(limit)
        )
    )
    count_conditions = [Sale.status == SaleStatus.completed]
    if start:
        count_conditions.append(Sale.occurred_at >= start)
    if end:
        count_conditions.append(Sale.occurred_at <= end)
    counts = {state.value: 0 for state in ReconciliationStatus}
    for state, count in db.execute(
        select(Sale.reconciliation_status, func.count(Sale.id))
        .where(*count_conditions)
        .group_by(Sale.reconciliation_status)
    ):
        counts[state.value if hasattr(state, "value") else str(state)] = count

    candidates, reviewed_pairs = find_duplicate_candidates(db, date_from=date_from, date_to=date_to)
    return {
        "items": [sale_out(sale) for sale in items],
        "total": counts.get(status.value, 0) if status else sum(counts.values()),
        "counts": counts,
        "candidates": candidates,
        "reviewed_pairs": reviewed_pairs,
    }


def review_duplicate(db: Session, payload: DuplicateReviewIn) -> DuplicateReview:
    a = db.get(Sale, payload.sale_a_id)
    b = db.get(Sale, payload.sale_b_id)
    if not a or not b:
        raise ValidationError("Both sales must exist to review a possible duplicate")

    review = db.scalar(
        select(DuplicateReview).where(
            DuplicateReview.sale_a_id == payload.sale_a_id,
            DuplicateReview.sale_b_id == payload.sale_b_id,
        )
    )
    now = utcnow()
    if review:
        review.status = payload.status
        review.notes = payload.notes
        review.resolved_at = now
    else:
        review = DuplicateReview(
            sale_a_id=payload.sale_a_id,
            sale_b_id=payload.sale_b_id,
            status=payload.status,
            notes=payload.notes,
            resolved_at=now,
        )
        db.add(review)

    if payload.status == DuplicateReviewStatus.confirmed_duplicate:
        for sale in (a, b):
            if sale.reconciliation_status != ReconciliationStatus.potential_duplicate:
                sale.reconciliation_status = ReconciliationStatus.potential_duplicate
                sale.version += 1
                db.add(
                    ReconciliationRecord(
                        sale_id=sale.id,
                        external_order_id=sale.external_order_id,
                        status=ReconciliationStatus.potential_duplicate,
                        notes=payload.notes or "Confirmed as a possible duplicate pair. Both records were kept.",
                        reviewed_at=now,
                    )
                )
        audit(
            db,
            entity_type="duplicate_review",
            entity_id=f"{payload.sale_a_id}-{payload.sale_b_id}",
            action="confirmed_duplicate",
            after={"sale_a_id": a.id, "sale_b_id": b.id, "status": payload.status.value},
            note=payload.notes,
        )
    else:
        audit(
            db,
            entity_type="duplicate_review",
            entity_id=f"{payload.sale_a_id}-{payload.sale_b_id}",
            action="dismissed",
            after={"sale_a_id": a.id, "sale_b_id": b.id, "status": payload.status.value},
            note=payload.notes,
        )
    db.flush()
    return review


def unverified_website_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(Sale.id)).where(
                Sale.source.in_([SaleSource.website, SaleSource.imported]),
                Sale.status == SaleStatus.completed,
                Sale.reconciliation_status == ReconciliationStatus.recorded,
            )
        )
        or 0
    )


def pending_candidate_count(db: Session) -> int:
    candidates, _ = find_duplicate_candidates(db, limit=500)
    return len(candidates)
