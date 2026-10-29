from __future__ import annotations

import csv
import io
import os
import shutil
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import BASE_DIR, settings
from app.errors import AppError, ValidationError
from app.models import (
    Expense,
    Payment,
    Product,
    ReconciliationRecord,
    Sale,
    SaleItem,
    SaleReturn,
    SaleStatus,
    StockMovement,
    StockReceipt,
    StockReceiptItem,
)
from app.services.money import ledger as money_ledger
from app.services.reports import monthly_summary, period_summary
from app.services.settings_service import category_label
from app.utils import business_tz, local_day, range_bounds_utc, utcnow

REQUIRED_TABLES = {
    "alembic_version",
    "products",
    "sales",
    "sale_items",
    "payments",
    "expenses",
    "stock_movements",
    "stock_receipts",
    "stock_receipt_items",
    "sale_returns",
    "sale_return_items",
    "deliveries",
    "cash_sessions",
    "cash_handovers",
    "reconciliation_records",
    "duplicate_reviews",
    "audit_logs",
    "sync_operations",
    "app_settings",
    "customers",
}


def database_path(db: Session) -> Path:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        raise AppError("Backup and restore are available only for SQLite databases.")
    raw = bind.url.database or "college_cart.db"
    path = Path(raw)
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return path


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def validate_sqlite_file(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise ValidationError("The uploaded backup file is empty or missing")
    try:
        connection = _connect_readonly(path)
    except sqlite3.Error as exc:
        raise ValidationError(f"The backup is not a readable SQLite database ({exc})") from exc
    try:
        check = connection.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise ValidationError("The SQLite integrity check failed. This backup is not safe to restore.")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValidationError(
                "The backup is missing required tables: " + ", ".join(sorted(missing))
            )
        version_row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        return {
            "integrity": "ok",
            "tables": sorted(tables),
            "alembic_version": version_row[0] if version_row else None,
            "size_bytes": path.stat().st_size,
        }
    finally:
        connection.close()


def _sqlite_backup(source_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source_path), timeout=15) as source:
        with sqlite3.connect(str(destination)) as target:
            source.backup(target)


def create_snapshot(db: Session, prefix: str = "backup") -> dict:
    db_path = database_path(db)
    if not db_path.exists():
        raise ValidationError("The database file does not exist yet")
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(business_tz()).strftime("%Y%m%d-%H%M%S")
    destination = settings.backups_dir / f"{prefix}-{db_path.stem[:16]}-{stamp}-{os.urandom(3).hex()}.db"
    _sqlite_backup(db_path, destination)
    return {
        "path": str(destination),
        "filename": destination.name,
        "size_bytes": destination.stat().st_size,
        "created_at": datetime.now(business_tz()).isoformat(),
    }


def backup_info(db: Session) -> dict:
    db_path = database_path(db)
    counts: dict[str, int] = {}
    if db_path.exists():
        with _connect_readonly(db_path) as connection:
            for table in [
                "products",
                "sales",
                "sale_items",
                "payments",
                "expenses",
                "stock_movements",
                "sale_returns",
                "stock_receipts",
                "cash_sessions",
                "cash_handovers",
                "deliveries",
                "customers",
                "money_transactions",
                "audit_logs",
            ]:
                try:
                    counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    counts[table] = 0
    return {
        "database_path": str(db_path),
        "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "last_modified": (
            datetime.fromtimestamp(db_path.stat().st_mtime).astimezone(business_tz())
            if db_path.exists()
            else None
        ),
        "table_counts": counts,
    }


def restore_from_file(db: Session, upload_path: Path) -> dict:
    db_path = database_path(db)
    info = validate_sqlite_file(upload_path)
    safety = create_snapshot(db, prefix="before-restore")
    safety_validation = validate_sqlite_file(Path(safety["path"]))
    if safety_validation["integrity"] != "ok":
        raise AppError("Could not create a valid safety backup. Restore was aborted.")

    from app.userdata import dispose_path

    db.close()
    dispose_path(db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(upload_path, db_path)
    _upgrade_schema(db_path)
    dispose_path(db_path)
    validate_sqlite_file(db_path)
    return {
        "restored": True,
        "safety_backup": safety["path"],
        "backup_version": info.get("alembic_version"),
    }


def _upgrade_schema(db_path: Path) -> None:
    from app.userdata import run_migrations

    run_migrations(f"sqlite:///{db_path.as_posix()}")


def import_backup_file(db: Session, upload_path: Path) -> dict:
    return restore_from_file(db, upload_path)


def _csv_safe(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = str(value)
    if text and text[0] in {"=", "+", "@", "\t", "\r"}:
        return "'" + text
    if text.startswith("-") and not text[1:2].isdigit():
        return "'" + text
    return text


def _local(value: datetime) -> str:
    return value.astimezone(business_tz()).strftime("%Y-%m-%d %H:%M")


def _csv_response(rows: list[list], headers: list[str]) -> str:
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_safe(value) for value in row])
    return buffer.getvalue()


def export_csv(
    db: Session,
    export_type: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, str]:
    start, end = range_bounds_utc(date_from, date_to)
    name = export_type.lower().strip()

    if name == "sales":
        stmt = (
            select(Sale)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.customer),
                selectinload(Sale.delivery),
                selectinload(Sale.payments),
            )
            .order_by(Sale.occurred_at)
        )
        if start:
            stmt = stmt.where(Sale.occurred_at >= start)
        if end:
            stmt = stmt.where(Sale.occurred_at <= end)
        sales = list(db.scalars(stmt))
        rows = []
        for sale in sales:
            items = "; ".join(f"{item.product_name} x{item.quantity}" for item in sale.items)
            rows.append(
                [
                    sale.id,
                    sale.uuid,
                    _local(sale.occurred_at),
                    sale.source.value,
                    sale.external_order_id or "",
                    sale.status.value,
                    sale.payment_status.value,
                    " / ".join(filter(None, [sale.customer.name if sale.customer else "", sale.customer_ref or ""])),
                    items,
                    sale.subtotal,
                    sale.discount,
                    sale.total,
                    sale.returned_value,
                    sale.amount_paid,
                    sale.refunded_amount,
                    sale.outstanding,
                    sale.delivery.status.value if sale.delivery else "none",
                    sale.reconciliation_status.value,
                    sale.notes or "",
                ]
            )
        content = _csv_response(
            rows,
            [
                "Sale ID",
                "UUID",
                "Occurred (local)",
                "Source",
                "Website order ID",
                "Status",
                "Payment status",
                "Customer",
                "Items",
                "Subtotal",
                "Discount",
                "Total",
                "Returned value",
                "Amount paid",
                "Refunded",
                "Outstanding",
                "Delivery",
                "Reconciliation",
                "Notes",
            ],
        )
        return content, "college-cart-sales.csv"

    if name == "inventory":
        products = list(db.scalars(select(Product).order_by(Product.name)))
        rows = [
            [
                p.id,
                p.name,
                p.category,
                p.sku or "",
                p.purchase_cost,
                p.selling_price,
                p.stock_quantity,
                p.low_stock_threshold,
                p.stock_value,
                p.retail_value,
                p.expiry_date.isoformat() if p.expiry_date else "",
                p.batch_note or "",
                "active" if p.is_active else "inactive",
                _local(p.created_at),
                _local(p.updated_at),
            ]
            for p in products
        ]
        content = _csv_response(
            rows,
            [
                "Product ID",
                "Name",
                "Category",
                "SKU",
                "Purchase cost",
                "Selling price",
                "Stock quantity",
                "Low stock threshold",
                "Stock value",
                "Retail value",
                "Expiry date",
                "Batch note",
                "Status",
                "Created",
                "Updated",
            ],
        )
        return content, "college-cart-inventory.csv"

    if name == "expenses":
        stmt = (
            select(Expense)
            .options(selectinload(Expense.stock_receipt))
            .order_by(Expense.occurred_at)
        )
        if start:
            stmt = stmt.where(Expense.occurred_at >= start)
        if end:
            stmt = stmt.where(Expense.occurred_at <= end)
        expenses = list(db.scalars(stmt))
        rows = [
            [
                e.id,
                _local(e.occurred_at),
                e.category,
                category_label(e.category),
                e.description,
                e.amount,
                e.method,
                e.paid_to or "",
                e.reference or "",
                "stock purchase" if e.stock_receipt else "ordinary",
                "void" if e.is_void else "active",
                e.void_reason or "",
                e.notes or "",
            ]
            for e in expenses
        ]
        content = _csv_response(
            rows,
            [
                "Expense ID",
                "Occurred (local)",
                "Category",
                "Category label",
                "Description",
                "Amount",
                "Method",
                "Paid to",
                "Reference",
                "Kind",
                "Status",
                "Void reason",
                "Notes",
            ],
        )
        return content, "college-cart-expenses.csv"

    if name == "payments":
        stmt = select(Payment).order_by(Payment.paid_at)
        if start:
            stmt = stmt.where(Payment.paid_at >= start)
        if end:
            stmt = stmt.where(Payment.paid_at <= end)
        payments = list(db.scalars(stmt))
        rows = [
            [
                p.id,
                p.sale_id or "",
                _local(p.paid_at),
                p.direction.value,
                p.kind.value,
                p.method,
                p.amount,
                p.reference or "",
                p.notes or "",
            ]
            for p in payments
        ]
        content = _csv_response(
            rows,
            ["Payment ID", "Sale ID", "Paid (local)", "Direction", "Kind", "Method", "Amount", "Reference", "Notes"],
        )
        return content, "college-cart-payments.csv"

    if name == "movements":
        stmt = (
            select(StockMovement)
            .options(selectinload(StockMovement.product))
            .order_by(StockMovement.occurred_at)
        )
        if start:
            stmt = stmt.where(StockMovement.occurred_at >= start)
        if end:
            stmt = stmt.where(StockMovement.occurred_at <= end)
        movements = list(db.scalars(stmt))
        rows = [
            [
                m.id,
                _local(m.occurred_at),
                m.product_id,
                m.product.name if m.product else "",
                m.movement_type.value,
                m.quantity_change,
                m.unit_cost or "",
                m.reason,
                m.sale_id or "",
                m.sale_return_id or "",
                m.stock_receipt_id or "",
                m.notes or "",
            ]
            for m in movements
        ]
        content = _csv_response(
            rows,
            [
                "Movement ID",
                "Occurred (local)",
                "Product ID",
                "Product",
                "Type",
                "Quantity change",
                "Unit cost",
                "Reason",
                "Sale ID",
                "Return ID",
                "Receipt ID",
                "Notes",
            ],
        )
        return content, "college-cart-stock-movements.csv"

    if name == "receivables":
        stmt = (
            select(Sale)
            .options(selectinload(Sale.customer))
            .where(Sale.status == SaleStatus.completed)
            .order_by(Sale.occurred_at)
        )
        if start:
            stmt = stmt.where(Sale.occurred_at >= start)
        if end:
            stmt = stmt.where(Sale.occurred_at <= end)
        rows = []
        for sale in db.scalars(stmt):
            if sale.outstanding > 0:
                rows.append(
                    [
                        sale.id,
                        _local(sale.occurred_at),
                        sale.customer.name if sale.customer else (sale.customer_ref or ""),
                        sale.total,
                        sale.returned_value,
                        sale.amount_paid,
                        sale.refunded_amount,
                        sale.outstanding,
                        sale.payment_status.value,
                        sale.source.value,
                    ]
                )
        content = _csv_response(
            rows,
            [
                "Sale ID",
                "Occurred (local)",
                "Customer",
                "Total",
                "Returned value",
                "Amount paid",
                "Refunded",
                "Outstanding",
                "Payment status",
                "Source",
            ],
        )
        return content, "college-cart-receivables.csv"

    if name == "reconciliation":
        stmt = (
            select(Sale)
            .options(selectinload(Sale.customer))
            .order_by(Sale.occurred_at)
        )
        if start:
            stmt = stmt.where(Sale.occurred_at >= start)
        if end:
            stmt = stmt.where(Sale.occurred_at <= end)
        rows = [
            [
                sale.id,
                _local(sale.occurred_at),
                sale.source.value,
                sale.external_order_id or "",
                sale.total,
                sale.customer.name if sale.customer else (sale.customer_ref or ""),
                sale.reconciliation_status.value,
                sale.status.value,
            ]
            for sale in db.scalars(stmt)
        ]
        content = _csv_response(
            rows,
            [
                "Sale ID",
                "Occurred (local)",
                "Source",
                "Website order ID",
                "Total",
                "Customer",
                "Reconciliation status",
                "Sale status",
            ],
        )
        return content, "college-cart-reconciliation.csv"

    if name in {"money", "money_history", "ledger"}:
        if date_from or date_to:
            start_day = date_from or date_to
            end_day = date_to or local_day(utcnow())
            result = money_ledger(
                db,
                range_name="custom",
                date_from=start_day,
                date_to=end_day,
                limit=100000,
                include_void=True,
            )
        else:
            result = money_ledger(db, range_name="all", limit=100000, include_void=True)
        rows = [
            [
                row["source"],
                row["record_id"],
                _local(row["occurred_at"]),
                row["direction"],
                row["amount"],
                row["method"],
                row["person"] or "",
                row["category"],
                row["category_label"],
                row["description"],
                row["reference"] or "",
                row["sale_id"] or "",
                row["expense_id"] or "",
                row["receipt_id"] or "",
                row["handover_id"] or "",
                row["money_id"] or "",
                "void" if row["is_void"] else "active",
                row["notes"] or "",
                _local(row["created_at"]) if row["created_at"] else "",
            ]
            for row in reversed(result["items"])
        ]
        content = _csv_response(
            rows,
            [
                "Entry type",
                "Entry ID",
                "Occurred (local)",
                "Direction",
                "Amount",
                "Method",
                "Person / party",
                "Category",
                "Category label",
                "Description",
                "Reference",
                "Sale ID",
                "Expense ID",
                "Receipt ID",
                "Handover ID",
                "Money transaction ID",
                "Status",
                "Notes",
                "Created (local)",
            ],
        )
        return content, "college-cart-money-history.csv"

    if name in {"monthly", "monthly_summary"}:
        year = (date_from or local_day(utcnow())).year
        rows = [
            [
                row["month"],
                row["label"],
                row["sales_count"],
                row["net_sales"],
                row["collected"],
                row["refunds"],
                row["ordinary_expenses"],
                row["stock_purchases"],
                row["money_in"],
                row["money_out"],
                row["outstanding"],
            ]
            for row in monthly_summary(db, year)
        ]
        content = _csv_response(
            rows,
            [
                "Month",
                "Month name",
                "Sales count",
                "Net sales",
                "Collected",
                "Refunds",
                "Ordinary expenses",
                "Stock purchases",
                "Money in",
                "Money out",
                "Outstanding",
            ],
        )
        return content, f"college-cart-monthly-{year}.csv"

    if name == "daily":
        if not date_from or not date_to:
            raise ValidationError("Daily report export requires date_from and date_to")
        summary = period_summary(db, date_from, date_to)
        rows = [
            [
                row["date"],
                row["sales_count"],
                row["gross_sales"],
                row["returns_value"],
                row["net_sales"],
                row["collected"],
                row["refunds"],
                row["ordinary_expenses"],
                row["stock_purchases"],
                row["money_in"],
                row["money_out"],
            ]
            for row in summary["daily"]
        ]
        content = _csv_response(
            rows,
            [
                "Date",
                "Sales count",
                "Gross sales",
                "Returns",
                "Net sales",
                "Collected",
                "Refunds",
                "Ordinary expenses",
                "Stock purchases",
                "Money in",
                "Money out",
            ],
        )
        return content, f"college-cart-daily-{date_from}-to-{date_to}.csv"

    raise ValidationError(
        "Unknown export type. Use sales, money, inventory, expenses, payments, movements, "
        "receivables, reconciliation, monthly or daily."
    )
