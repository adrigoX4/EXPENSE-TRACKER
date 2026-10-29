from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MovementType
from app.schemas import (
    MovementPage,
    ProductCreate,
    ProductListOut,
    ProductOut,
    ProductUpdate,
)
from app.serializers import movement_out, product_out
from app.services.inventory import list_movements
from app.services.products import (
    create_product,
    get_product,
    list_products,
    product_categories,
    update_product,
)

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    return product_categories(db)


@router.get("", response_model=ProductListOut)
def index(
    search: str | None = None,
    category: str | None = None,
    active: bool | None = None,
    low_stock: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, cats = list_products(
        db,
        search=search,
        category=category,
        active=active,
        low_stock=low_stock,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [product_out(product) for product in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "categories": cats,
    }


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create(payload: ProductCreate, response: Response, db: Session = Depends(get_db)):
    product = create_product(db, payload)
    db.commit()
    response.headers["Location"] = f"/api/products/{product.id}"
    return product_out(product)


@router.get("/{product_id}", response_model=ProductOut)
def detail(product_id: int, db: Session = Depends(get_db)):
    return product_out(get_product(db, product_id))


@router.patch("/{product_id}", response_model=ProductOut)
def patch(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = update_product(db, product_id, payload)
    db.commit()
    return product_out(product)


@router.get("/{product_id}/movements", response_model=MovementPage)
def product_movements(
    product_id: int,
    movement_type: MovementType | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    get_product(db, product_id)
    items, total = list_movements(
        db,
        product_id=product_id,
        movement_type=movement_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [movement_out(movement) for movement in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
