from __future__ import annotations

from decimal import Decimal

from app.models import (
    CashHandover,
    Delivery,
    Expense,
    MoneyTransaction,
    Payment,
    PaymentDirection,
    PaymentKind,
    Product,
    Sale,
    SaleItem,
    SaleReturn,
    StockMovement,
    StockReceipt,
)


def product_out(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "sku": p.sku,
        "purchase_cost": p.purchase_cost,
        "selling_price": p.selling_price,
        "stock_quantity": p.stock_quantity,
        "low_stock_threshold": p.low_stock_threshold,
        "expiry_date": p.expiry_date,
        "batch_note": p.batch_note,
        "is_active": p.is_active,
        "version": p.version,
        "is_low_stock": p.stock_quantity <= p.low_stock_threshold,
        "stock_value": p.stock_value,
        "retail_value": p.retail_value,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id,
        "uuid": p.uuid,
        "sale_id": p.sale_id,
        "amount": p.amount,
        "direction": p.direction,
        "kind": p.kind,
        "method": p.method,
        "paid_at": p.paid_at,
        "reference": p.reference,
        "notes": p.notes,
        "created_at": p.created_at,
    }


def sale_item_out(item: SaleItem) -> dict:
    return {
        "id": item.id,
        "product_id": item.product_id,
        "product_name": item.product_name,
        "sku": item.sku,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "unit_cost": item.unit_cost,
        "line_discount": item.line_discount,
        "line_total": item.line_total,
        "cost_total": item.cost_total,
        "returned_quantity": item.returned_quantity,
        "remaining_quantity": item.quantity - item.returned_quantity,
    }


def return_out(r: SaleReturn) -> dict:
    return {
        "id": r.id,
        "uuid": r.uuid,
        "sale_id": r.sale_id,
        "returned_at": r.returned_at,
        "reason": r.reason,
        "restock": r.restock,
        "refund_amount": r.refund_amount,
        "refund_method": r.refund_method,
        "notes": r.notes,
        "returned_value": r.returned_value,
        "cost_value": r.cost_value,
        "items": [
            {
                "id": item.id,
                "sale_item_id": item.sale_item_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_value": item.line_value,
                "cost_total": item.cost_total,
                "product_name": item.sale_item.product_name if item.sale_item else None,
            }
            for item in r.items
        ],
    }


def delivery_out(d: Delivery) -> dict:
    return {
        "id": d.id,
        "sale_id": d.sale_id,
        "status": d.status,
        "delivery_person": d.delivery_person,
        "notes": d.notes,
        "dispatched_at": d.dispatched_at,
        "delivered_at": d.delivered_at,
        "version": d.version,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


def _payment_method_summary(sale: Sale) -> str | None:
    totals: dict[str, Decimal] = {}
    for payment in sale.payments:
        if payment.direction != PaymentDirection.inflow or payment.kind == PaymentKind.refund:
            continue
        totals[payment.method] = totals.get(payment.method, Decimal("0.00")) + payment.amount
    if not totals:
        return None
    return ", ".join(
        f"{method} {amount.quantize(Decimal('0.01'))}" for method, amount in sorted(totals.items())
    )


def _items_summary(sale: Sale) -> str | None:
    if not sale.items:
        return None
    parts = [f"{item.product_name} × {item.quantity}" for item in sale.items[:3]]
    if len(sale.items) > 3:
        parts.append(f"+{len(sale.items) - 3} more")
    return ", ".join(parts)


def sale_out(sale: Sale) -> dict:
    delivery = sale.delivery
    customer = sale.customer
    return {
        "id": sale.id,
        "uuid": sale.uuid,
        "occurred_at": sale.occurred_at,
        "source": sale.source,
        "external_order_id": sale.external_order_id,
        "subtotal": sale.subtotal,
        "discount": sale.discount,
        "total": sale.total,
        "returned_value": sale.returned_value,
        "amount_paid": sale.amount_paid,
        "refunded_amount": sale.refunded_amount,
        "net_paid": sale.net_paid,
        "outstanding": sale.outstanding,
        "payment_status": sale.payment_status,
        "status": sale.status,
        "customer_id": sale.customer_id,
        "customer_name": customer.name if customer else sale.customer_ref,
        "customer_ref": customer.name if customer else sale.customer_ref,
        "notes": sale.notes,
        "delivery_status": delivery.status.value if delivery else "none",
        "delivery_person": delivery.delivery_person if delivery else None,
        "reconciliation_status": sale.reconciliation_status,
        "item_count": len(sale.items),
        "items_summary": _items_summary(sale),
        "payment_methods_summary": _payment_method_summary(sale),
        "version": sale.version,
        "is_pending_sync": False,
        "created_at": sale.created_at,
        "updated_at": sale.updated_at,
    }


def sale_detail_out(sale: Sale) -> dict:
    data = sale_out(sale)
    data.update(
        {
            "items": [sale_item_out(item) for item in sale.items],
            "payments": [payment_out(p) for p in sale.payments],
            "returns": [return_out(r) for r in sale.returns],
            "delivery": delivery_out(sale.delivery) if sale.delivery else None,
            "customer": (
                {
                    "id": sale.customer.id,
                    "name": sale.customer.name,
                    "phone": sale.customer.phone,
                    "room_ref": sale.customer.room_ref,
                    "notes": sale.customer.notes,
                }
                if sale.customer
                else None
            ),
            "void_reason": sale.void_reason,
            "voided_at": sale.voided_at,
        }
    )
    return data


def delivery_row_out(d: Delivery) -> dict:
    data = delivery_out(d)
    sale = d.sale
    customer_name = sale.customer.name if sale.customer else sale.customer_ref
    data.update(
        {
            "sale_uuid": sale.uuid,
            "occurred_at": sale.occurred_at,
            "customer_name": customer_name,
            "total": sale.total,
            "outstanding": sale.outstanding,
            "payment_status": sale.payment_status,
            "item_count": len(sale.items),
        }
    )
    return data


def expense_out(e: Expense) -> dict:
    receipt = e.stock_receipt
    is_stock = receipt is not None or e.category == "inventory_purchase"
    return {
        "id": e.id,
        "uuid": e.uuid,
        "occurred_at": e.occurred_at,
        "category": e.category,
        "description": e.description,
        "amount": e.amount,
        "method": e.method,
        "paid_to": e.paid_to,
        "kind": "stock_purchase" if is_stock else "ordinary",
        "linked_receipt_id": receipt.id if receipt else None,
        "reference": e.reference,
        "notes": e.notes,
        "is_void": e.is_void,
        "void_reason": e.void_reason,
        "voided_at": e.voided_at,
        "version": e.version,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def money_transaction_out(t: MoneyTransaction) -> dict:
    return {
        "id": t.id,
        "uuid": t.uuid,
        "direction": t.direction,
        "amount": t.amount,
        "person": t.person,
        "category": t.category,
        "method": t.method,
        "occurred_at": t.occurred_at,
        "description": t.description,
        "reference": t.reference,
        "notes": t.notes,
        "is_void": t.is_void,
        "void_reason": t.void_reason,
        "voided_at": t.voided_at,
        "version": t.version,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def movement_out(m: StockMovement) -> dict:
    return {
        "id": m.id,
        "uuid": m.uuid,
        "product_id": m.product_id,
        "product_name": m.product.name if m.product else None,
        "movement_type": m.movement_type,
        "quantity_change": m.quantity_change,
        "unit_cost": m.unit_cost,
        "occurred_at": m.occurred_at,
        "reason": m.reason,
        "sale_id": m.sale_id,
        "sale_return_id": m.sale_return_id,
        "stock_receipt_id": m.stock_receipt_id,
        "notes": m.notes,
        "created_at": m.created_at,
    }


def receipt_out(r: StockReceipt) -> dict:
    return {
        "id": r.id,
        "uuid": r.uuid,
        "received_at": r.received_at,
        "supplier_ref": r.supplier_ref,
        "total_cost": r.total_cost,
        "payment_method": r.payment_method,
        "notes": r.notes,
        "expense_id": r.expense_id,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "line_total": item.line_total,
            }
            for item in r.items
        ],
    }


def handover_out(h: CashHandover) -> dict:
    return {
        "id": h.id,
        "uuid": h.uuid,
        "amount": h.amount,
        "method": h.method,
        "recipient": h.recipient,
        "handed_at": h.handed_at,
        "reference": h.reference,
        "notes": h.notes,
        "created_at": h.created_at,
    }


def money_or_zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0.00")
