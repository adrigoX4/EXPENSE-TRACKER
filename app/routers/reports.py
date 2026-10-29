from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DashboardOut, MonthlyReportOut, ReportSummaryOut
from app.services.backup import export_csv
from app.services.reports import dashboard, monthly_summary, period_summary, resolve_range

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports/summary", response_model=ReportSummaryOut)
def summary(
    range_name: str | None = Query(default="today", alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    start, end, _ = resolve_range(range_name, date_from, date_to)
    return period_summary(db, start, end)


@router.get("/reports/daily", response_model=ReportSummaryOut)
def daily(
    range_name: str | None = Query(default="7d", alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    start, end, _ = resolve_range(range_name, date_from, date_to)
    return period_summary(db, start, end)


@router.get("/reports/monthly", response_model=MonthlyReportOut)
def monthly(year: int | None = None, db: Session = Depends(get_db)):
    from app.utils import local_day, utcnow

    if year is None:
        year = local_day(utcnow()).year
    return {"year": year, "months": monthly_summary(db, year)}


@router.get("/reports/export")
def export(
    export_type: str = Query(alias="type"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    content, filename = export_csv(db, export_type, date_from=date_from, date_to=date_to)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard_view(
    range_name: str | None = Query(default="today", alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return dashboard(db, range_name, date_from, date_to)
