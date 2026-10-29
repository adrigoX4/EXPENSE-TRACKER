from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ValidationError
from app.models import (
    Expense,
    MoneyTransaction,
    Payment,
    PaymentDirection,
    PaymentKind,
    Sale,
    SaleReturn,
    SaleReturnItem,
    SaleStatus,
    StockReceipt,
)
from app.serializers import sale_out
from app.services.cash import pending_balances
from app.services.money import ledger as money_ledger
from app.services.products import inventory_summary
from app.services.ranges import resolve_range
from app.services.reconciliation import pending_candidate_count, unverified_website_count
from app.services.settings_service import category_label, money_category_label
from app.utils import local_day, money, month_bounds, range_bounds_utc, utcnow

ZERO = Decimal("0.00")


def _load_sales(db: Session, start, end) -> list[Sale]:
    return list(
        db.scalars(
            select(Sale)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.returns),
                selectinload(Sale.delivery),
                selectinload(Sale.customer),
            )
            .where(
                Sale.occurred_at >= start,
                Sale.occurred_at <= end,
                Sale.status == SaleStatus.completed,
            )
            .order_by(Sale.occurred_at)
        )
    )


def _load_returns(db: Session, start, end) -> list[SaleReturn]:
    return list(
        db.scalars(
            select(SaleReturn)
            .options(selectinload(SaleReturn.items).selectinload(SaleReturnItem.sale_item))
            .where(SaleReturn.returned_at >= start, SaleReturn.returned_at <= end)
        )
    )


def _empty_day(day: date) -> dict:
    return {
        "date": day,
        "sales_count": 0,
        "gross_sales": ZERO,
        "returns_value": ZERO,
        "net_sales": ZERO,
        "collected": ZERO,
        "refunds": ZERO,
        "ordinary_expenses": ZERO,
        "stock_purchases": ZERO,
        "money_in": ZERO,
        "money_out": ZERO,
    }


def period_summary(db: Session, date_from: date, date_to: date) -> dict:
    if date_from > date_to:
        raise ValidationError("date_from must be on or before date_to")
    start, end = range_bounds_utc(date_from, date_to)
    sales = _load_sales(db, start, end)
    returns = _load_returns(db, start, end)
    expenses = list(
        db.scalars(
            select(Expense)
            .options(selectinload(Expense.stock_receipt))
            .where(
                Expense.occurred_at >= start,
                Expense.occurred_at <= end,
                Expense.is_void.is_(False),
            )
        )
    )
    payments = list(
        db.scalars(select(Payment).where(Payment.paid_at >= start, Payment.paid_at <= end))
    )
    receipts = list(
        db.scalars(
            select(StockReceipt)
            .options(selectinload(StockReceipt.items))
            .where(StockReceipt.received_at >= start, StockReceipt.received_at <= end)
        )
    )
    ledger_result = money_ledger(
        db,
        range_name="custom",
        date_from=date_from,
        date_to=date_to,
        limit=1,
    )
    money_summary = ledger_result["summary"]
    money_by_day = {row["date"]: row for row in ledger_result["daily"]}

    gross_sales = money(sum((sale.total for sale in sales), ZERO))
    returns_value = money(sum((sale_return.returned_value for sale_return in returns), ZERO))
    net_sales = money(gross_sales - returns_value)
    collected = money(
        sum(
            (
                payment.amount
                for payment in payments
                if payment.direction == PaymentDirection.inflow
                and payment.kind == PaymentKind.sale_payment
            ),
            ZERO,
        )
    )
    refunds = money(
        sum(
            (
                payment.amount
                for payment in payments
                if payment.direction == PaymentDirection.outflow
            ),
            ZERO,
        )
    )
    outstanding = money(sum((sale.outstanding for sale in sales), ZERO))
    average_sale = money(gross_sales / len(sales)) if sales else ZERO

    daily_map: dict[date, dict] = {}
    for sale in sales:
        day = local_day(sale.occurred_at)
        row = daily_map.setdefault(day, _empty_day(day))
        row["gross_sales"] += sale.total
        row["sales_count"] += 1
    for sale_return in returns:
        day = local_day(sale_return.returned_at)
        row = daily_map.setdefault(day, _empty_day(day))
        row["returns_value"] += sale_return.returned_value
    for expense in expenses:
        day = local_day(expense.occurred_at)
        row = daily_map.setdefault(day, _empty_day(day))
        is_stock = expense.stock_receipt is not None or expense.category == "inventory_purchase"
        if is_stock:
            row["stock_purchases"] += expense.amount
        else:
            row["ordinary_expenses"] += expense.amount
    for payment in payments:
        day = local_day(payment.paid_at)
        row = daily_map.setdefault(day, _empty_day(day))
        if payment.direction == PaymentDirection.inflow and payment.kind == PaymentKind.sale_payment:
            row["collected"] += payment.amount
        elif payment.direction == PaymentDirection.outflow:
            row["refunds"] += payment.amount
    for day, money_row in money_by_day.items():
        row = daily_map.setdefault(day, _empty_day(day))
        row["money_in"] = money_row["money_in"]
        row["money_out"] = money_row["money_out"]

    day_count = (date_to - date_from).days + 1
    if day_count <= 62:
        days = [date_from + timedelta(days=index) for index in range(day_count)]
    else:
        days = sorted(daily_map)
    daily = []
    for day in days:
        row = daily_map.get(day, _empty_day(day))
        row["net_sales"] = money(row["gross_sales"] - row["returns_value"])
        daily.append(
            {
                "date": day.isoformat(),
                "sales_count": row["sales_count"],
                "gross_sales": money(row["gross_sales"]),
                "returns_value": money(row["returns_value"]),
                "net_sales": money(row["net_sales"]),
                "collected": money(row["collected"]),
                "refunds": money(row["refunds"]),
                "ordinary_expenses": money(row["ordinary_expenses"]),
                "stock_purchases": money(row["stock_purchases"]),
                "money_in": money(row["money_in"]),
                "money_out": money(row["money_out"]),
            }
        )

    product_rows: dict[int, dict] = {}
    for sale in sales:
        for item in sale.items:
            row = product_rows.setdefault(
                item.product_id,
                {
                    "product_id": item.product_id,
                    "name": item.product_name,
                    "quantity": 0,
                    "revenue": ZERO,
                },
            )
            row["quantity"] += item.quantity
            row["revenue"] += item.line_total
    for sale_return in returns:
        for item in sale_return.items:
            sale_item = item.sale_item
            if not sale_item:
                continue
            row = product_rows.setdefault(
                sale_item.product_id,
                {
                    "product_id": sale_item.product_id,
                    "name": sale_item.product_name,
                    "quantity": 0,
                    "revenue": ZERO,
                },
            )
            row["quantity"] -= item.quantity
            row["revenue"] -= item.line_value
    top_products = []
    for row in product_rows.values():
        top_products.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "quantity": row["quantity"],
                "revenue": money(row["revenue"]),
            }
        )
    top_products.sort(key=lambda row: (row["quantity"], row["revenue"]), reverse=True)

    method_rows: dict[str, dict] = {}
    for payment in payments:
        row = method_rows.setdefault(
            payment.method,
            {"method": payment.method, "inflow": ZERO, "outflow": ZERO, "count": 0},
        )
        if payment.direction == PaymentDirection.inflow:
            row["inflow"] += payment.amount
        else:
            row["outflow"] += payment.amount
        row["count"] += 1
    payment_methods = []
    for row in method_rows.values():
        row["inflow"] = money(row["inflow"])
        row["outflow"] = money(row["outflow"])
        row["net"] = money(row["inflow"] - row["outflow"])
        payment_methods.append(row)
    payment_methods.sort(key=lambda row: row["net"], reverse=True)

    category_rows: dict[str, dict] = {}
    for expense in expenses:
        is_stock = expense.stock_receipt is not None or expense.category == "inventory_purchase"
        key = "inventory_purchase" if is_stock else expense.category
        row = category_rows.setdefault(
            key,
            {
                "category": key,
                "label": "Stock purchase" if is_stock else category_label(key),
                "amount": ZERO,
                "count": 0,
            },
        )
        row["amount"] += expense.amount
        row["count"] += 1
    expense_categories = []
    for row in category_rows.values():
        row["amount"] = money(row["amount"])
        expense_categories.append(row)
    expense_categories.sort(key=lambda row: row["amount"], reverse=True)

    ordinary_expenses = money(money_summary["ordinary_expenses"])
    stock_purchases = money(money_summary["stock_purchases"])
    return {
        "date_from": date_from,
        "date_to": date_to,
        "sales_count": len(sales),
        "gross_sales": gross_sales,
        "returns_value": returns_value,
        "net_sales": net_sales,
        "collected": collected,
        "refunds": refunds,
        "ordinary_expenses": ordinary_expenses,
        "stock_purchases": stock_purchases,
        "total_expenses": money(ordinary_expenses + stock_purchases),
        "money_in": money(money_summary["money_in"]),
        "money_out": money(money_summary["money_out"]),
        "outstanding": outstanding,
        "average_sale": average_sale,
        "cash_in": money(money_summary["cash_in"]),
        "cash_out": money(money_summary["cash_out"]),
        "upi_in": money(money_summary["upi_in"]),
        "upi_out": money(money_summary["upi_out"]),
        "cash_balance": money(money_summary["current_cash"]),
        "upi_balance": money(money_summary["current_upi"]),
        "balance_complete": bool(money_summary["balance_complete"]),
        "daily": daily,
        "top_products": top_products[:12],
        "payment_methods": payment_methods,
        "expense_categories": expense_categories,
    }


def _activity_items(db: Session) -> list[dict]:
    items: list[dict] = []
    sales = list(
        db.scalars(
            select(Sale)
            .options(selectinload(Sale.items), selectinload(Sale.customer))
            .order_by(Sale.occurred_at.desc(), Sale.id.desc())
            .limit(6)
        )
    )
    for sale in sales:
        items.append(
            {
                "type": "sale",
                "title": f"Sale #{sale.id}",
                "description": f"{len(sale.items)} item(s)"
                + (f" · {sale.customer.name}" if sale.customer else ""),
                "amount": money(sale.total),
                "direction": "sale",
                "occurred_at": sale.occurred_at,
                "link": f"/sales/{sale.id}",
            }
        )
    payments = list(
        db.scalars(
            select(Payment)
            .options(selectinload(Payment.sale).selectinload(Sale.customer))
            .order_by(Payment.paid_at.desc(), Payment.id.desc())
            .limit(6)
        )
    )
    for payment in payments:
        sale = payment.sale
        person = sale.customer.name if sale and sale.customer else (sale.customer_ref if sale else None)
        incoming = payment.direction == PaymentDirection.inflow
        items.append(
            {
                "type": "payment",
                "title": "Payment received" if incoming else "Refund issued",
                "description": f"{payment.method.upper()}" + (f" · {person}" if person else ""),
                "amount": money(payment.amount),
                "direction": "in" if incoming else "out",
                "occurred_at": payment.paid_at,
                "link": f"/sales/{payment.sale_id}" if payment.sale_id else None,
            }
        )
    expenses = list(
        db.scalars(
            select(Expense)
            .options(selectinload(Expense.stock_receipt))
            .where(Expense.is_void.is_(False))
            .order_by(Expense.occurred_at.desc(), Expense.id.desc())
            .limit(6)
        )
    )
    for expense in expenses:
        is_stock = expense.stock_receipt is not None or expense.category == "inventory_purchase"
        items.append(
            {
                "type": "expense",
                "title": "Stock purchase" if is_stock else "Expense paid",
                "description": (
                    "Stock purchase"
                    if is_stock
                    else category_label(expense.category)
                )
                + (f" · {expense.paid_to}" if expense.paid_to else ""),
                "amount": money(expense.amount),
                "direction": "out",
                "occurred_at": expense.occurred_at,
                "link": f"/expenses?focus={expense.id}",
            }
        )
    returns = list(
        db.scalars(
            select(SaleReturn).order_by(SaleReturn.returned_at.desc(), SaleReturn.id.desc()).limit(6)
        )
    )
    for sale_return in returns:
        items.append(
            {
                "type": "return",
                "title": f"Return on sale #{sale_return.sale_id}",
                "description": sale_return.reason,
                "amount": money(sale_return.refund_amount),
                "direction": "out",
                "occurred_at": sale_return.returned_at,
                "link": f"/sales/{sale_return.sale_id}",
            }
        )
    transactions = list(
        db.scalars(
            select(MoneyTransaction)
            .order_by(MoneyTransaction.occurred_at.desc(), MoneyTransaction.id.desc())
            .limit(6)
        )
    )
    for transaction in transactions:
        items.append(
            {
                "type": "money",
                "title": money_category_label(transaction.category),
                "description": transaction.description
                + (f" · {transaction.person}" if transaction.person else ""),
                "amount": money(transaction.amount),
                "direction": "in" if transaction.direction.value == "in" else "out",
                "occurred_at": transaction.occurred_at,
                "link": f"/money-history?focus={transaction.id}",
            }
        )
    items.sort(key=lambda item: item["occurred_at"], reverse=True)
    return items[:5]


def dashboard(db: Session, range_name: str | None, date_from: date | None, date_to: date | None) -> dict:
    start, end, label = resolve_range(range_name, date_from, date_to)
    summary = period_summary(db, start, end)
    inventory = inventory_summary(db)
    current_money = money_ledger(db, range_name="all", limit=1)["summary"]
    pending_total = pending_balances(db)

    due = Sale.total - Sale.returned_value - (Sale.amount_paid - Sale.refunded_amount)
    pending_sales = list(
        db.scalars(
            select(Sale)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.returns),
                selectinload(Sale.delivery),
                selectinload(Sale.customer),
            )
            .where(Sale.status == SaleStatus.completed, due > 0)
            .order_by(Sale.occurred_at.desc(), Sale.id.desc())
            .limit(6)
        )
    )

    recent_money = money_ledger(db, range_name="all", limit=6)["items"]

    return {
        "range": label,
        "date_from": start,
        "date_to": end,
        "summary": summary,
        "money_received": summary["money_in"],
        "sale_payments_received": summary["collected"],
        "other_money_received": money(summary["money_in"] - summary["collected"]),
        "ordinary_expenses": summary["ordinary_expenses"],
        "total_money_in": summary["money_in"],
        "total_money_out": summary["money_out"],
        "cash_available": summary["cash_balance"],
        "upi_available": summary["upi_balance"],
        "balance_complete": summary["balance_complete"],
        "opening_cash": current_money["opening_cash"],
        "opening_upi": current_money["opening_upi"],
        "opening_effective_date": current_money["opening_effective_date"],
        "outstanding_total": pending_total,
        "low_stock_count": inventory["low_stock_count"],
        "out_of_stock_count": inventory["out_of_stock_count"],
        "unverified_website_orders": unverified_website_count(db),
        "potential_duplicates": pending_candidate_count(db),
        "recent_activity": _activity_items(db),
        "recent_money": recent_money,
        "pending_payments": [sale_out(sale) for sale in pending_sales[:5]],
        "low_stock_products": inventory["low_stock_products"],
    }


def monthly_summary(db: Session, year: int) -> list[dict]:
    rows = []
    today = local_day(utcnow())
    for month in range(1, 13):
        first, last = month_bounds(year, month)
        if first > today:
            break
        if last > today:
            last = today
        summary = period_summary(db, first, last)
        rows.append(
            {
                "month": month,
                "label": calendar.month_name[month],
                "sales_count": summary["sales_count"],
                "net_sales": summary["net_sales"],
                "collected": summary["collected"],
                "refunds": summary["refunds"],
                "ordinary_expenses": summary["ordinary_expenses"],
                "stock_purchases": summary["stock_purchases"],
                "money_in": summary["money_in"],
                "money_out": summary["money_out"],
                "outstanding": summary["outstanding"],
            }
        )
    return rows
