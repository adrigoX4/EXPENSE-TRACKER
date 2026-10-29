from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ReconciliationStatus
from app.schemas import (
    DuplicateCandidate,
    DuplicateReviewIn,
    ReconciliationLink,
    ReconciliationQueue,
    ReconciliationRecordOut,
    ReconciliationUpdate,
    SaleOut,
)
from app.serializers import sale_out
from app.services.reconciliation import (
    find_duplicate_candidates,
    link_external,
    list_records,
    queue,
    review_duplicate,
    update_reconciliation,
)

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.get("/queue", response_model=ReconciliationQueue)
def get_queue(
    date_from: date | None = None,
    date_to: date | None = None,
    status: ReconciliationStatus | None = None,
    db: Session = Depends(get_db),
):
    return queue(db, date_from=date_from, date_to=date_to, status=status)


@router.get("/candidates", response_model=list[DuplicateCandidate])
def candidates(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    rows, _ = find_duplicate_candidates(db, date_from=date_from, date_to=date_to)
    return rows


@router.get("/records", response_model=list[ReconciliationRecordOut])
def records(sale_id: int | None = None, db: Session = Depends(get_db)):
    return list_records(db, sale_id=sale_id)


@router.patch("/sales/{sale_id}", response_model=SaleOut)
def patch_sale(sale_id: int, payload: ReconciliationUpdate, db: Session = Depends(get_db)):
    sale = update_reconciliation(db, sale_id, payload)
    return sale_out(sale)


@router.post("/link", response_model=SaleOut)
def link(payload: ReconciliationLink, db: Session = Depends(get_db)):
    sale = link_external(db, payload)
    return sale_out(sale)


@router.post("/duplicates/review")
def review(payload: DuplicateReviewIn, db: Session = Depends(get_db)):
    review_row = review_duplicate(db, payload)
    db.commit()
    return {
        "id": review_row.id,
        "sale_a_id": review_row.sale_a_id,
        "sale_b_id": review_row.sale_b_id,
        "status": review_row.status.value,
        "notes": review_row.notes,
    }
