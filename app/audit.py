from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in fields:
        if hasattr(obj, field):
            data[field] = _jsonable(getattr(obj, field))
    return data


def audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: int | str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        before_json=json.dumps(_jsonable(before), ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(_jsonable(after), ensure_ascii=False) if after is not None else None,
        note=note,
    )
    db.add(entry)
    return entry
