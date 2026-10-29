from __future__ import annotations

from datetime import date, timedelta

from app.errors import ValidationError
from app.utils import local_day, utcnow


def resolve_range(
    range_name: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date, str]:
    today = local_day(utcnow())
    name = (range_name or "today").lower()
    if name == "today":
        return today, today, "Today"
    if name == "yesterday":
        day = today - timedelta(days=1)
        return day, day, "Yesterday"
    if name in {"7d", "last7", "last_7_days"}:
        return today - timedelta(days=6), today, "Last 7 days"
    if name in {"30d", "last30", "last_30_days"}:
        return today - timedelta(days=29), today, "Last 30 days"
    if name == "month":
        return today.replace(day=1), today, "This month"
    if name in {"previous_month", "prev_month", "last_month"}:
        first_this_month = today.replace(day=1)
        last_previous = first_this_month - timedelta(days=1)
        return last_previous.replace(day=1), last_previous, "Previous month"
    if name == "custom":
        if not date_from or not date_to:
            raise ValidationError("Custom ranges require date_from and date_to")
        if date_from > date_to:
            raise ValidationError("date_from must be on or before date_to")
        return date_from, date_to, "Custom range"
    if date_from or date_to:
        start = date_from or date_to
        end = date_to or date_from
        if start > end:
            raise ValidationError("date_from must be on or before date_to")
        return start, end, "Custom range"
    return today, today, "Today"
