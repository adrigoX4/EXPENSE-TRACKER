from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.errors import ValidationError
from app.models import AppSetting, MoneyDirection
from app.utils import money, utcnow

SETTINGS_KEY = "app"
SETTINGS_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "business_name": "College Cart",
    "payment_methods": ["cash", "upi"],
    "expense_categories": [
        "inventory_purchase",
        "travel",
        "food",
        "packaging",
        "personal_other",
        "miscellaneous",
    ],
    "money_in_categories": [
        "customer_payment",
        "money_from_owner",
        "repayment_received",
        "other_money_received",
    ],
    "money_out_categories": [
        "money_to_owner",
        "stock_purchase",
        "expense_payment",
        "cash_handover",
        "repayment_given",
        "other_money_given",
    ],
    "default_low_stock_threshold": 5,
    "opening_cash_balance": None,
    "opening_upi_balance": None,
    "opening_balance_date": None,
    "currency": "INR",
    "inventory_category": "inventory_purchase",
    "settings_version": SETTINGS_VERSION,
}

CATEGORY_LABELS = {
    "inventory_purchase": "Stock purchase",
    "travel": "Travel",
    "food": "Food & refreshments",
    "packaging": "Packaging",
    "personal_other": "Personal / other",
    "miscellaneous": "Miscellaneous",
    "delivery": "Delivery / transport",
    "other": "Other",
}

TRANSFER_CATEGORY = "cash_upi_transfer"

MONEY_CATEGORY_LABELS = {
    TRANSFER_CATEGORY: "Transfer between cash & UPI",
    "customer_payment": "Customer payment",
    "money_from_owner": "Money received from owner",
    "repayment_received": "Repayment received",
    "other_money_received": "Other money received",
    "money_to_owner": "Money given to owner",
    "stock_purchase": "Stock purchase",
    "expense_payment": "Expense payment",
    "cash_handover": "Cash handover",
    "repayment_given": "Repayment given",
    "other_money_given": "Other money given",
    "adjustment": "Cash / UPI adjustment",
    "refund": "Sale refund",
}


def _normalize_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = value.strip().lower().replace(" ", "_").replace("-", "_")
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _upgrade_stored(stored: dict[str, Any]) -> dict[str, Any]:
    if int(stored.get("settings_version") or 1) >= SETTINGS_VERSION:
        return stored
    upgraded = dict(stored)
    categories = list(upgraded.get("expense_categories") or DEFAULTS["expense_categories"])
    for category in ("travel", "food", "personal_other"):
        if category not in categories:
            categories.append(category)
    upgraded["expense_categories"] = categories
    upgraded["settings_version"] = SETTINGS_VERSION
    return upgraded


def get_settings(db: Session) -> dict[str, Any]:
    row = db.get(AppSetting, SETTINGS_KEY)
    data = copy.deepcopy(DEFAULTS)
    if row:
        try:
            stored = json.loads(row.value_json)
            if isinstance(stored, dict):
                data.update(_upgrade_stored(stored))
        except (ValueError, TypeError):
            pass
    data["business_timezone"] = app_settings.business_timezone
    data["currency"] = "INR"
    data.setdefault("inventory_category", "inventory_purchase")
    data.setdefault("default_low_stock_threshold", 5)
    data.setdefault("settings_version", SETTINGS_VERSION)
    if "cash" not in data.get("payment_methods", []):
        data.setdefault("payment_methods", []).insert(0, "cash")
    if data.get("inventory_category") not in data.get("expense_categories", []):
        data.setdefault("expense_categories", []).insert(0, data["inventory_category"])
    for key in ("money_in_categories", "money_out_categories", "expense_categories", "payment_methods"):
        if not data.get(key):
            data[key] = list(DEFAULTS[key])
    return data


def _clean_optional_money(value: Decimal | str | None, label: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = money(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a valid amount") from exc
    if amount < 0:
        raise ValidationError(f"{label} cannot be negative")
    return amount


def save_settings(
    db: Session,
    *,
    business_name: str,
    payment_methods: list[str],
    expense_categories: list[str],
    money_in_categories: list[str] | None = None,
    money_out_categories: list[str] | None = None,
    default_low_stock_threshold: int | None = None,
    opening_cash_balance: Decimal | None = None,
    opening_upi_balance: Decimal | None = None,
    opening_balance_date: date | None = None,
    opening_fields: set[str] | None = None,
    clear_opening_balances: bool = False,
) -> dict:
    current = get_settings(db)
    methods = _normalize_list(payment_methods)
    if "cash" not in methods:
        methods.insert(0, "cash")
    categories = _normalize_list(expense_categories)
    if "inventory_purchase" not in categories:
        categories.insert(0, "inventory_purchase")
    money_in = (
        _normalize_list(money_in_categories)
        if money_in_categories is not None
        else list(current["money_in_categories"])
    )
    money_out = (
        _normalize_list(money_out_categories)
        if money_out_categories is not None
        else list(current["money_out_categories"])
    )

    if not business_name.strip():
        raise ValidationError("Business name is required")
    if not methods:
        raise ValidationError("At least one payment method is required")
    if not categories:
        raise ValidationError("At least one expense category is required")
    if not money_in:
        raise ValidationError("At least one money-in category is required")
    if not money_out:
        raise ValidationError("At least one money-out category is required")
    if default_low_stock_threshold is not None and default_low_stock_threshold < 0:
        raise ValidationError("Default low-stock threshold cannot be negative")

    data = {
        **current,
        "business_name": business_name.strip(),
        "payment_methods": methods,
        "expense_categories": categories,
        "money_in_categories": money_in,
        "money_out_categories": money_out,
        "default_low_stock_threshold": (
            default_low_stock_threshold
            if default_low_stock_threshold is not None
            else current.get("default_low_stock_threshold", 5)
        ),
        "settings_version": SETTINGS_VERSION,
    }
    if clear_opening_balances:
        data["opening_cash_balance"] = None
        data["opening_upi_balance"] = None
        data["opening_balance_date"] = None
    else:
        explicit = opening_fields or set()
        if "opening_cash_balance" in explicit:
            cash = _clean_optional_money(opening_cash_balance, "Opening cash balance")
            data["opening_cash_balance"] = str(cash) if cash is not None else None
        else:
            data["opening_cash_balance"] = current.get("opening_cash_balance")
        if "opening_upi_balance" in explicit:
            upi = _clean_optional_money(opening_upi_balance, "Opening UPI balance")
            data["opening_upi_balance"] = str(upi) if upi is not None else None
        else:
            data["opening_upi_balance"] = current.get("opening_upi_balance")
        if "opening_balance_date" in explicit:
            data["opening_balance_date"] = (
                opening_balance_date.isoformat() if opening_balance_date else None
            )
        else:
            data["opening_balance_date"] = current.get("opening_balance_date")
        has_opening = (
            data["opening_cash_balance"] is not None or data["opening_upi_balance"] is not None
        )
        if has_opening and not data["opening_balance_date"]:
            raise ValidationError(
                "Opening balance date is required when an opening cash or UPI balance is set"
            )
    data["inventory_category"] = "inventory_purchase"

    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value_json=json.dumps(data))
        db.add(row)
    else:
        row.value_json = json.dumps(data)
        row.updated_at = utcnow()
    db.flush()
    return get_settings(db)


def allowed_methods(db: Session) -> list[str]:
    return get_settings(db)["payment_methods"]


def validate_method(db: Session, method: str) -> str:
    normalized = method.strip().lower()
    if normalized not in allowed_methods(db):
        raise ValidationError(
            f"Payment method '{normalized}' is not configured. Add it in Settings or use one of: "
            + ", ".join(allowed_methods(db))
        )
    return normalized


def validate_expense_category(db: Session, category: str) -> str:
    normalized = category.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized not in get_settings(db)["expense_categories"]:
        raise ValidationError(
            f"Expense category '{normalized}' is not configured. Add it in Settings."
        )
    return normalized


def validate_money_category(db: Session, direction: MoneyDirection, category: str) -> str:
    normalized = category.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized == TRANSFER_CATEGORY:
        if direction != MoneyDirection.outflow:
            raise ValidationError(
                "A cash↔UPI transfer is recorded once, as money out of the source method. It is not money in."
            )
        return normalized
    data = get_settings(db)
    key = "money_in_categories" if direction == MoneyDirection.inflow else "money_out_categories"
    if normalized not in data[key]:
        raise ValidationError(
            f"Money category '{normalized}' is not configured for this direction. Add it in Settings."
        )
    return normalized


def inventory_category(db: Session) -> str:
    return get_settings(db)["inventory_category"]


def category_label(value: str) -> str:
    return CATEGORY_LABELS.get(value, value.replace("_", " ").title())


def money_category_label(value: str) -> str:
    return MONEY_CATEGORY_LABELS.get(value, CATEGORY_LABELS.get(value, value.replace("_", " ").title()))


def default_payment_method(db: Session) -> str:
    methods = allowed_methods(db)
    return methods[0] if methods else "cash"


def ensure_defaults_installed(db: Session) -> None:
    row = db.scalar(select(AppSetting).where(AppSetting.key == SETTINGS_KEY))
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value_json=json.dumps(DEFAULTS)))
        db.commit()
    elif int(json.loads(row.value_json).get("settings_version") or 1) < SETTINGS_VERSION:
        upgraded = _upgrade_stored(json.loads(row.value_json))
        row.value_json = json.dumps(upgraded)
        db.commit()
