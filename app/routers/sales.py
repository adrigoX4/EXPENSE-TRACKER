from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.models import (
    AuditLog,
    DeliveryStatus,
    PaymentStatus,
    ReconciliationStatus,
    SaleSource,
    SaleStatus,
)
from app.schemas import (
    AuditOut,
    PaymentCreate,
    PaymentOut,
    PaymentWithSaleOut,
    ReturnWithSaleOut,
    SaleCreate,
    SaleDetailOut,
    SalePage,
    SaleReturnCreate,
    SaleUpdate,
    SaleVoidIn,
)
from app.serializers import payment_out, return_out, sale_detail_out, sale_out
from app.services.sales import (
    add_payment,
    create_return,
    create_sale,
    find_sale_by_external_id,
    get_sale,
    list_sales,
    update_sale,
    void_sale,
)

router = APIRouter(prefix="/api/sales", tags=["sales"])


def _validate_delivery_filter(value: str | None) -> str | None:
    if value is None:
        return None
    valid = {state.value for state in DeliveryStatus} | {"none"}
    if value not in valid:
        raise ValidationError(f"delivery_status must be one of: {', '.join(sorted(valid))}")
    return value


@router.get("/check-external")
def check_external(external_order_id: str, db: Session = Depends(get_db)):
    sale = find_sale_by_external_id(db, external_order_id)
    return {
        "exists": sale is not None,
        "sale": sale_out(sale) if sale else None,
    }


@router.post("", response_model=SaleDetailOut, status_code=status.HTTP_201_CREATED)
def create(
    payload: SaleCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    sale, created = create_sale(db, payload, header_idempotency_key=idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    else:
        response.headers["Location"] = f"/api/sales/{sale.id}"
    return sale_detail_out(sale)


@router.get("", response_model=SalePage)
def index(
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    source: SaleSource | None = None,
    status_filter: SaleStatus | None = Query(default=None, alias="status"),
    payment_status: PaymentStatus | None = None,
    delivery_status: str | None = None,
    reconciliation_status: ReconciliationStatus | None = None,
    product_id: int | None = None,
    has_external_id: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    delivery_status = _validate_delivery_filter(delivery_status)
    items, total, aggregates = list_sales(
        db,
        search=search,
        date_from=date_from,
        date_to=date_to,
        source=source,
        status=status_filter,
        payment_status=payment_status,
        delivery_status=delivery_status,
        reconciliation_status=reconciliation_status,
        product_id=product_id,
        has_external_id=has_external_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [sale_out(sale) for sale in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "aggregates": aggregates,
    }


@router.get("/{sale_id}", response_model=SaleDetailOut)
def detail(sale_id: int, db: Session = Depends(get_db)):
    return sale_detail_out(get_sale(db, sale_id))


@router.patch("/{sale_id}", response_model=SaleDetailOut)
def patch(sale_id: int, payload: SaleUpdate, db: Session = Depends(get_db)):
    sale = update_sale(db, sale_id, payload)
    db.commit()
    return sale_detail_out(sale)


@router.post("/{sale_id}/void", response_model=SaleDetailOut)
def void(sale_id: int, payload: SaleVoidIn, db: Session = Depends(get_db)):
    sale = void_sale(db, sale_id, payload)
    db.commit()
    return sale_detail_out(sale)


@router.get("/{sale_id}/payments", response_model=list[PaymentOut])
def payments(sale_id: int, db: Session = Depends(get_db)):
    sale = get_sale(db, sale_id)
    return [payment_out(payment) for payment in sale.payments]


@router.post("/{sale_id}/payments", response_model=PaymentWithSaleOut, status_code=status.HTTP_201_CREATED)
def add_sale_payment(
    sale_id: int,
    payload: PaymentCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    sale, payment, created = add_payment(
        db,
        sale_id,
        amount=payload.amount,
        method=payload.method,
        paid_at=payload.paid_at,
        reference=payload.reference,
        notes=payload.notes,
        idempotency_key=idempotency_key or payload.idempotency_key,
    )
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    return {"payment": payment_out(payment), "sale": sale_detail_out(get_sale(db, sale.id))}


@router.post("/{sale_id}/returns", response_model=ReturnWithSaleOut, status_code=status.HTTP_201_CREATED)
def add_return(
    sale_id: int,
    payload: SaleReturnCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    sale, sale_return, created = create_return(db, sale_id, payload)
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    detail_data = sale_detail_out(get_sale(db, sale.id))
    matching = next((row for row in detail_data["returns"] if row["id"] == sale_return.id), None)
    return {"return": matching or return_out(sale_return), "sale": detail_data}


@router.get("/{sale_id}/audit", response_model=list[AuditOut])
def sale_audit(sale_id: int, db: Session = Depends(get_db)):
    get_sale(db, sale_id)
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "sale", AuditLog.entity_id == str(sale_id))
        .order_by(AuditLog.changed_at.desc(), AuditLog.id.desc())
        .limit(100)
    )
    return list(rows)
