from __future__ import annotations


def test_sale_records_items_payment_stock_and_audit(client, product):
    chips = product(name="Chips", price="20.00", cost="12.00", stock=50)
    response = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": chips["id"], "quantity": 2}],
            "initial_payment": {"amount": "40.00", "method": "cash"},
            "customer_name": "Asha",
        },
    )
    assert response.status_code == 201, response.text
    sale = response.json()
    assert sale["total"] == "40.00"
    assert sale["subtotal"] == "40.00"
    assert sale["payment_status"] == "paid"
    assert sale["outstanding"] == "0.00"
    assert sale["source"] == "manual"
    assert sale["uuid"]
    assert sale["item_count"] == 1
    assert sale["customer_name"] == "Asha"
    assert sale["items"][0]["product_name"] == "Chips"
    assert sale["items"][0]["unit_cost"] == "12.00"
    assert sale["items"][0]["cost_total"] == "24.00"
    assert len(sale["payments"]) == 1

    refreshed = client.get(f"/api/products/{chips['id']}").json()
    assert refreshed["stock_quantity"] == 48

    movements = client.get("/api/inventory/movements", params={"product_id": chips["id"]}).json()
    types = [row["movement_type"] for row in movements["items"]]
    assert types.count("opening") == 1
    assert types.count("sale") == 1

    audit = client.get(f"/api/sales/{sale['id']}/audit").json()
    assert any(row["action"] == "created" for row in audit)
    product_audit = client.get("/api/audit", params={"entity_type": "product"}).json()
    assert any(row["action"] == "stock_sold" for row in product_audit)


def test_partial_payment_and_additional_payments(client, product):
    item = product(price="50.00", stock=10)
    response = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payment": {"amount": "30.00", "method": "upi"},
        },
    )
    sale = response.json()
    assert sale["total"] == "100.00"
    assert sale["payment_status"] == "partial"
    assert sale["outstanding"] == "70.00"
    assert sale["net_paid"] == "30.00"

    payment = client.post(
        f"/api/sales/{sale['id']}/payments",
        json={"amount": "70.00", "method": "cash"},
        headers={"Idempotency-Key": "pay-sale-1-full"},
    )
    assert payment.status_code == 201, payment.text
    updated = payment.json()["sale"]
    assert updated["payment_status"] == "paid"
    assert updated["outstanding"] == "0.00"
    assert updated["version"] == sale["version"] + 1


def test_sale_idempotency_key_prevents_duplicates(client, product):
    item = product(stock=10)
    payload = {"items": [{"product_id": item["id"], "quantity": 1}]}
    headers = {"Idempotency-Key": "offline-sale-abc"}

    first = client.post("/api/sales", json=payload, headers=headers)
    second = client.post("/api/sales", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotency-Replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]

    refreshed = client.get(f"/api/products/{item['id']}").json()
    assert refreshed["stock_quantity"] == 9

    sales = client.get("/api/sales").json()
    assert sales["total"] == 1

    operations = client.get("/api/sync/operations").json()
    assert operations["total"] == 1
    assert operations["items"][0]["operation_id"] == "offline-sale-abc"
    assert operations["items"][0]["attempts"] == 2


def test_sale_client_uuid_prevents_duplicate_retry(client, product):
    item = product(stock=10)
    payload = {"items": [{"product_id": item["id"], "quantity": 1}], "client_uuid": "3e8e8e8e-1111-4222-8333-444455556666"}
    first = client.post("/api/sales", json=payload)
    second = client.post("/api/sales", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 9


def test_duplicate_external_order_id_is_blocked(client, product):
    item = product(stock=10)
    first = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "source": "website",
            "external_order_id": "CC-2026-1001",
        },
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "source": "website",
            "external_order_id": "cc-2026-1001",
        },
    )
    assert duplicate.status_code == 409
    body = duplicate.json()["error"]
    assert body["code"] == "duplicate_external_order_id"
    assert body["details"]["existing_sale"]["sale_id"] == first.json()["id"]

    check = client.get("/api/sales/check-external", params={"external_order_id": "CC-2026-1001"}).json()
    assert check["exists"] is True


def test_negative_stock_requires_explicit_override_and_reason(client, product):
    item = product(stock=1)
    payload = {"items": [{"product_id": item["id"], "quantity": 5}]}
    blocked = client.post("/api/sales", json=payload)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "negative_stock"

    missing_reason = client.post("/api/sales", json={**payload, "allow_negative_stock": True})
    assert missing_reason.status_code == 422
    assert "reason is required" in missing_reason.text.lower()

    allowed = client.post(
        "/api/sales",
        json={
            **payload,
            "allow_negative_stock": True,
            "negative_stock_reason": "Stock count was not updated before this sale",
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == -4

    audit = client.get(f"/api/sales/{allowed.json()['id']}/audit").json()
    created = next(entry for entry in audit if entry["action"] == "created")
    assert "Stock count was not updated" in created["note"]


def test_return_restocks_and_refunds_without_exceeding_limits(client, product):
    item = product(price="20.00", cost="12.00", stock=10)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 3}],
            "initial_payment": {"amount": "60.00", "method": "cash"},
        },
    ).json()
    sale_item_id = sale["items"][0]["id"]

    response = client.post(
        f"/api/sales/{sale['id']}/returns",
        json={
            "items": [{"sale_item_id": sale_item_id, "quantity": 1}],
            "reason": "Damaged packet",
            "restock": True,
            "refund_amount": "20.00",
            "refund_method": "cash",
            "idempotency_key": "return-1",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["return"]["returned_value"] == "20.00"
    assert body["return"]["cost_value"] == "12.00"
    assert body["sale"]["returned_value"] == "20.00"
    assert body["sale"]["refunded_amount"] == "20.00"
    assert body["sale"]["net_paid"] == "40.00"
    assert body["sale"]["outstanding"] == "0.00"
    assert body["sale"]["items"][0]["returned_quantity"] == 1
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 8

    replay = client.post(
        f"/api/sales/{sale['id']}/returns",
        json={
            "items": [{"sale_item_id": sale_item_id, "quantity": 1}],
            "reason": "Damaged packet",
            "restock": True,
            "refund_amount": "20.00",
            "refund_method": "cash",
            "idempotency_key": "return-1",
        },
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"

    too_many = client.post(
        f"/api/sales/{sale['id']}/returns",
        json={"items": [{"sale_item_id": sale_item_id, "quantity": 3}], "reason": "Too many"},
    )
    assert too_many.status_code == 422
    assert "Only 2 remain" in too_many.json()["error"]["message"]


def test_void_restocks_refunds_and_marks_voided(client, product):
    item = product(price="20.00", stock=10)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payment": {"amount": "40.00", "method": "cash"},
        },
    ).json()
    response = client.post(
        f"/api/sales/{sale['id']}/void",
        json={"version": sale["version"], "reason": "Entered on the wrong date", "restock": True, "refund_paid": True},
    )
    assert response.status_code == 200, response.text
    voided = response.json()
    assert voided["status"] == "voided"
    assert voided["payment_status"] == "voided"
    assert voided["outstanding"] == "0.00"
    assert voided["refunded_amount"] == "40.00"
    assert voided["void_reason"] == "Entered on the wrong date"
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 10

    again = client.post(f"/api/sales/{sale['id']}/void", json={"reason": "Again"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_voided"


def test_filters_aggregates_and_version_conflict(client, product):
    item = product(price="10.00", stock=20)
    first = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payment": {"amount": "5.00", "method": "cash"},
            "customer_ref": "Room A",
        },
    ).json()
    client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "10.00", "method": "upi"},
            "source": "website",
            "external_order_id": "CC-WEB-7",
        },
    )

    listed = client.get("/api/sales", params={"payment_status": "partial"}).json()
    assert listed["total"] == 1
    assert listed["aggregates"]["revenue"] == "20.00"
    assert listed["aggregates"]["collected"] == "5.00"
    assert listed["aggregates"]["outstanding"] == "15.00"

    by_source = client.get("/api/sales", params={"source": "website"}).json()
    assert by_source["total"] == 1

    by_product = client.get("/api/sales", params={"product_id": item["id"]}).json()
    assert by_product["total"] == 2

    search = client.get("/api/sales", params={"search": "room a"}).json()
    assert search["total"] == 1

    conflict = client.patch(f"/api/sales/{first['id']}", json={"version": 999, "notes": "nope"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "version_conflict"

    updated = client.patch(f"/api/sales/{first['id']}", json={"version": first["version"], "notes": "Called back"})
    assert updated.status_code == 200
    assert updated.json()["notes"] == "Called back"
    assert updated.json()["version"] == first["version"] + 1


def test_sale_cannot_exceed_discount_or_payment(client, product):
    item = product(price="10.00", stock=5)
    over_discount = client.post(
        "/api/sales",
        json={"items": [{"product_id": item["id"], "quantity": 1}], "discount": "11.00"},
    )
    assert over_discount.status_code == 422
    over_payment = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "11.00", "method": "cash"},
        },
    )
    assert over_payment.status_code == 422
    missing = client.post("/api/sales", json={"items": [{"product_id": 999, "quantity": 1}]})
    assert missing.status_code == 422


def test_sale_with_delivery_and_voided_sale_excluded_from_reports(client, product, today):
    item = product(price="20.00", stock=10)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "20.00", "method": "cash"},
            "delivery_status": "out_for_delivery",
            "delivery_person": "Ravi",
        },
    ).json()
    assert sale["delivery_status"] == "out_for_delivery"
    assert sale["delivery_person"] == "Ravi"

    client.post(f"/api/sales/{sale['id']}/void", json={"reason": "Test cancellation"})

    summary = client.get(
        "/api/reports/summary",
        params={"range": "custom", "date_from": today.isoformat(), "date_to": today.isoformat()},
    ).json()
    assert summary["sales_count"] == 0
    assert summary["gross_sales"] == "0.00"
