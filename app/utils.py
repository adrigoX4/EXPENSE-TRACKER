from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from app.config import settings

MONEY_QUANT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | float | str | None) -> Decimal:
    """Convert a value to a rounded 2-decimal Decimal (banker-safe half-up)."""
    if value is None:
        return ZERO
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def business_tz() -> ZoneInfo:
    return ZoneInfo(settings.business_timezone)


def local_day(value: datetime) -> date:
    return ensure_utc(value).astimezone(business_tz()).date()


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    tz = business_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time.max, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def range_bounds_utc(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    start = day_bounds_utc(date_from)[0] if date_from else None
    end = day_bounds_utc(date_to)[1] if date_to else None
    return start, end


def month_bounds(year: int, month: int) -> tuple[date, date]:
    import calendar

    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def round_money(value: Decimal) -> Decimal:
    return money(value)


def percent(part: Decimal, whole: Decimal) -> float:
    if whole == 0:
        return 0.0
    return float((part / whole * 100).quantize(Decimal("0.1")))
