from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit, snapshot
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import Product, StockMovement, MovementType
from app.schemas import ProductCreate, ProductUpdate
from app.serializers import product_out
from app.services.settings_service import get_settings, validate_expense_category, validate_method
from app.utils import money, utcnow

PRODUCT_FIELDS = [
    "name",
    "category",
    "sku",
    "purchase_cost",
    "selling_price",
    "stock_quantity",
    "low_stock_threshold",
    "expiry_date",
    "batch_note",
    "is_active",
    "version",
]


def _ensure_sku_available(db: Session, sku: str | None, exclude_id: int | None = None) -> None:
    if not sku:
        return
    stmt = select(Product).where(func.lower(Product.sku) == sku.lower())
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    if db.scalar(stmt):
        raise ConflictError(f"SKU '{sku}' is already used by another product.", code="duplicate_sku")


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise NotFoundError("Product not found")
    return product


def list_products(
    db: Session,
    *,
    search: str | None = None,
    category: str | None = None,
    active: bool | None = True,
    low_stock: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Product], int, list[str]]:
    conditions = []
    if search:
        term = f"%{search.strip().lower()}%"
        conditions.append(or_(func.lower(Product.name).like(term), func.lower(func.coalesce(Product.sku, "")).like(term)))
    if category:
        conditions.append(Product.category == category)
    if active is not None:
        conditions.append(Product.is_active == active)
    if low_stock:
        conditions.append(Product.stock_quantity <= Product.low_stock_threshold)

    count_stmt = select(func.count(Product.id))
    stmt = select(Product)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        stmt = stmt.where(*conditions)

    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(
            stmt.order_by(Product.is_active.desc(), func.lower(Product.name), Product.id)
            .limit(limit)
            .offset(offset)
        )
    )
    categories = list(db.scalars(select(Product.category).distinct().order_by(Product.category)))
    return items, total, categories


def create_product(db: Session, payload: ProductCreate) -> Product:
    _ensure_sku_available(db, payload.sku)
    product = Product(
        name=payload.name,
        category=payload.category or "Uncategorized",
        sku=payload.sku,
        purchase_cost=money(payload.purchase_cost),
        selling_price=money(payload.selling_price),
        stock_quantity=payload.opening_stock,
        low_stock_threshold=payload.low_stock_threshold,
        expiry_date=payload.expiry_date,
        batch_note=payload.batch_note,
        is_active=payload.is_active,
        version=1,
    )
    db.add(product)
    db.flush()

    if payload.opening_stock > 0:
        db.add(
            StockMovement(
                product_id=product.id,
                movement_type=MovementType.opening,
                quantity_change=payload.opening_stock,
                unit_cost=money(payload.purchase_cost),
                occurred_at=utcnow(),
                reason="Opening stock",
            )
        )

    audit(
        db,
        entity_type="product",
        entity_id=product.id,
        action="created",
        after=snapshot(product, PRODUCT_FIELDS),
    )
    db.flush()
    return product


def update_product(db: Session, product_id: int, payload: ProductUpdate) -> Product:
    product = get_product(db, product_id)
    if product.version != payload.version:
        raise ConflictError(
            "This product was changed elsewhere. Reload it and try again.",
            code="version_conflict",
            details={"current": product_out(product)},
        )
    before = snapshot(product, PRODUCT_FIELDS)

    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "sku" in changes:
        _ensure_sku_available(db, changes["sku"], exclude_id=product.id)
    for field, value in changes.items():
        if field in {"purchase_cost", "selling_price"} and value is not None:
            value = money(value)
        if field == "name" and not value:
            raise ValidationError("Product name is required")
        if field == "category" and not value:
            value = "Uncategorized"
        if field in {"name", "category", "sku", "batch_note"} and value == "":
            value = None if field in {"sku", "batch_note"} else value
        setattr(product, field, value)
    if product.name is None:
        raise ValidationError("Product name is required")

    product.version += 1
    audit(
        db,
        entity_type="product",
        entity_id=product.id,
        action="updated",
        before=before,
        after=snapshot(product, PRODUCT_FIELDS),
    )
    db.flush()
    return product


def product_categories(db: Session) -> list[str]:
    return list(db.scalars(select(Product.category).distinct().order_by(Product.category)))


def inventory_summary(db: Session) -> dict:
    products = list(db.scalars(select(Product)))
    low = sorted(
        [p for p in products if p.is_active and p.stock_quantity <= p.low_stock_threshold],
        key=lambda p: (p.stock_quantity, p.name.lower()),
    )
    return {
        "product_count": len(products),
        "active_product_count": sum(1 for p in products if p.is_active),
        "low_stock_count": len([p for p in low if p.stock_quantity > 0]),
        "out_of_stock_count": sum(1 for p in products if p.is_active and p.stock_quantity <= 0),
        "total_units": sum(p.stock_quantity for p in products if p.is_active),
        "stock_value": money(sum((p.stock_value for p in products if p.is_active), Decimal("0"))),
        "retail_value": money(sum((p.retail_value for p in products if p.is_active), Decimal("0"))),
        "low_stock_products": [product_out(p) for p in low[:12]],
    }


def settings_reference(db: Session) -> dict:
    return get_settings(db)
