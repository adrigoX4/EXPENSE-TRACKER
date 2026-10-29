"""Development-only seed for clearly fictional demonstration products.

This script never seeds sales, payments or expenses. Run explicitly with:
    python -m app.seed
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Product
from app.schemas import ProductCreate
from app.services.products import create_product

DEMO_PRODUCTS = [
    {
        "name": "Demo Kurkure Masala Munch",
        "category": "Snacks",
        "sku": "DEMO-KURKURE",
        "purchase_cost": Decimal("14.00"),
        "selling_price": Decimal("20.00"),
        "opening_stock": 40,
        "low_stock_threshold": 10,
        "batch_note": "Fictional demonstration stock",
    },
    {
        "name": "Demo Chips - Classic Salted",
        "category": "Snacks",
        "sku": "DEMO-CHIPS-SALT",
        "purchase_cost": Decimal("10.00"),
        "selling_price": Decimal("15.00"),
        "opening_stock": 50,
        "low_stock_threshold": 12,
        "batch_note": "Fictional demonstration stock",
    },
    {
        "name": "Demo Munch Chocolate",
        "category": "Chocolate",
        "sku": "DEMO-MUNCH",
        "purchase_cost": Decimal("6.00"),
        "selling_price": Decimal("10.00"),
        "opening_stock": 60,
        "low_stock_threshold": 15,
        "batch_note": "Fictional demonstration stock",
    },
    {
        "name": "Demo Packaged Sweet Box",
        "category": "Sweets",
        "sku": "DEMO-SWEET-BOX",
        "purchase_cost": Decimal("45.00"),
        "selling_price": Decimal("70.00"),
        "opening_stock": 15,
        "low_stock_threshold": 5,
        "batch_note": "Fictional demonstration stock",
    },
]


def seed_products() -> int:
    db = SessionLocal()
    try:
        existing = db.scalar(select(func.count(Product.id))) or 0
        if existing:
            return 0
        for item in DEMO_PRODUCTS:
            create_product(db, ProductCreate(**item))
        db.commit()
        return len(DEMO_PRODUCTS)
    finally:
        db.close()


if __name__ == "__main__":
    count = seed_products()
    print(f"Seeded {count} demonstration products." if count else "Seed skipped: products already exist.")
