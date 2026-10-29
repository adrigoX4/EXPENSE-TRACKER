from __future__ import annotations

from decimal import Decimal


def test_product_creation_opening_stock_and_summary(client, product):
    chips = product(name="Chips", cost="10.00", price="15.00", stock=10, low=4)
    assert chips["stock_quantity"] == 10
    assert chips["stock_value"] == "100.00"
    assert chips["retail_value"] == "150.00"

    empty = product(name="Cola", cost="20.00", price="30.00", stock=0, low=5)
    product(name="Munch", cost="5.00", price="10.00", stock=2, low=5)

    summary = client.get("/api/inventory/summary").json()
    assert summary["product_count"] == 3
    assert summary["active_product_count"] == 3
    assert summary["out_of_stock_count"] == 1
    assert summary["low_stock_count"] == 1
    assert summary["total_units"] == 12
    assert summary["stock_value"] == "110.00"
    low_names = [row["name"] for row in summary["low_stock_products"]]
    assert low_names == ["Cola", "Munch"]

    movements = client.get("/api/inventory/movements", params={"product_id": chips["id"]}).json()
    assert movements["total"] == 1
    assert movements["items"][0]["movement_type"] == "opening"
    assert movements["items"][0]["quantity_change"] == 10
    assert movements["items"][0]["unit_cost"] == "10.00"
    assert empty["stock_quantity"] == 0


def test_stock_receipt_updates_weighted_cost_and_creates_one_expense(client, product):
    item = product(cost="10.00", price="20.00", stock=10)
    response = client.post(
        "/api/inventory/receipts",
        json={
            "supplier_ref": "Wholesale Market",
            "payment_method": "cash",
            "items": [{"product_id": item["id"], "quantity": 10, "unit_cost": "14.00"}],
            "idempotency_key": "receipt-001",
        },
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["total_cost"] == "140.00"
    assert receipt["expense_id"]
    assert receipt["items"][0]["line_total"] == "140.00"

    refreshed = client.get(f"/api/products/{item['id']}").json()
    assert refreshed["stock_quantity"] == 20
    assert refreshed["purchase_cost"] == "12.00"

    replay = client.post(
        "/api/inventory/receipts",
        json={
            "supplier_ref": "Wholesale Market",
            "payment_method": "cash",
            "items": [{"product_id": item["id"], "quantity": 10, "unit_cost": "14.00"}],
            "idempotency_key": "receipt-001",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == receipt["id"]
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 20

    expenses = client.get("/api/expenses").json()
    assert expenses["total"] == 1
    assert expenses["items"][0]["category"] == "inventory_purchase"
    assert expenses["items"][0]["amount"] == "140.00"
    assert expenses["totals"]["amount"] == "140.00"

    movements = client.get("/api/inventory/movements", params={"movement_type": "receipt"}).json()
    assert movements["total"] == 1
    assert movements["items"][0]["stock_receipt_id"] == receipt["id"]

    linked_edit = client.patch(f"/api/expenses/{receipt['expense_id']}", json={"version": 1, "amount": "1.00"})
    assert linked_edit.status_code == 409
    assert linked_edit.json()["error"]["code"] == "linked_stock_expense"


def test_manual_movements_guard_negative_stock_and_validate_types(client, product):
    item = product(stock=3)
    damage = client.post(
        "/api/inventory/movements",
        json={
            "product_id": item["id"],
            "movement_type": "damage",
            "quantity_change": -7,
            "reason": "Water damage",
        },
    )
    assert damage.status_code == 409
    assert damage.json()["error"]["code"] == "negative_stock"

    override = client.post(
        "/api/inventory/movements",
        json={
            "product_id": item["id"],
            "movement_type": "damage",
            "quantity_change": -7,
            "reason": "Water damage",
            "allow_negative_stock": True,
        },
    )
    assert override.status_code == 201
    assert override.json()["movement_type"] == "damage"

    correction = client.post(
        "/api/inventory/movements",
        json={
            "product_id": item["id"],
            "movement_type": "correction",
            "quantity_change": 10,
            "reason": "Physical count correction",
            "idempotency_key": "movement-correction-1",
        },
    )
    assert correction.status_code == 201
    replay = client.post(
        "/api/inventory/movements",
        json={
            "product_id": item["id"],
            "movement_type": "correction",
            "quantity_change": 10,
            "reason": "Physical count correction",
            "idempotency_key": "movement-correction-1",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == correction.json()["id"]
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 6

    positive_damage = client.post(
        "/api/inventory/movements",
        json={"product_id": item["id"], "movement_type": "damage", "quantity_change": 2, "reason": "Wrong sign"},
    )
    assert positive_damage.status_code == 422
    zero = client.post(
        "/api/inventory/movements",
        json={"product_id": item["id"], "movement_type": "correction", "quantity_change": 0, "reason": "Nothing"},
    )
    assert zero.status_code == 422


def test_product_search_filters_update_and_duplicate_sku(client, product):
    item = product(name="Masala Chips", sku="CHIPS-1", stock=2, low=5)
    other = product(name="Sweet Box", sku="SWEET-1", stock=30, low=5)

    searched = client.get("/api/products", params={"search": "masala"}).json()
    assert searched["total"] == 1
    low = client.get("/api/products", params={"low_stock": True}).json()
    assert low["total"] == 1
    assert low["items"][0]["id"] == item["id"]

    duplicate = client.post(
        "/api/products",
        json={
            "name": "Duplicate",
            "category": "Snacks",
            "sku": "chips-1",
            "purchase_cost": "1.00",
            "selling_price": "2.00",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_sku"

    conflict = client.patch(f"/api/products/{item['id']}", json={"version": 99, "selling_price": "21.00"})
    assert conflict.status_code == 409
    updated = client.patch(f"/api/products/{item['id']}", json={"version": item["version"], "selling_price": "21.00"})
    assert updated.status_code == 200
    assert updated.json()["selling_price"] == "21.00"

    deactivated = client.patch(f"/api/products/{other['id']}", json={"version": other["version"], "is_active": False})
    assert deactivated.status_code == 200
    active = client.get("/api/products", params={"active": True}).json()
    assert active["total"] == 1


def test_receipt_validation_and_inactive_product(client, product):
    item = product(stock=5)
    empty = client.post(
        "/api/inventory/receipts",
        json={"payment_method": "cash", "items": []},
    )
    assert empty.status_code == 422

    bad_method = client.post(
        "/api/inventory/receipts",
        json={
            "payment_method": "crypto",
            "items": [{"product_id": item["id"], "quantity": 1, "unit_cost": "10.00"}],
        },
    )
    assert bad_method.status_code == 422
    assert "not configured" in bad_method.json()["error"]["message"]

    client.patch(f"/api/products/{item['id']}", json={"version": item["version"], "is_active": False})
    inactive = client.post(
        "/api/inventory/receipts",
        json={
            "payment_method": "cash",
            "items": [{"product_id": item["id"], "quantity": 1, "unit_cost": "10.00"}],
        },
    )
    assert inactive.status_code == 409
    assert inactive.json()["error"]["code"] == "product_inactive"
    assert Decimal("5") == Decimal(client.get(f"/api/products/{item['id']}").json()["stock_quantity"])
