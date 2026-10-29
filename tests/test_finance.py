from __future__ import annotations


def range_today(today):
    return {"range": "custom", "date_from": today.isoformat(), "date_to": today.isoformat()}


def set_settings(client, **extra):
    payload = {
        "business_name": "College Cart",
        "payment_methods": ["cash", "upi"],
        "expense_categories": ["inventory_purchase", "travel", "food", "miscellaneous"],
    }
    payload.update(extra)
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_uses_sales_money_and_expenses_without_profit_terms(client, product, today):
    item = product(cost="10.00", price="20.00", stock=100)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 5}],
            "initial_payment": {"amount": "100.00", "method": "cash"},
        },
    ).json()

    returned = client.post(
        f"/api/sales/{sale['id']}/returns",
        json={
            "items": [{"sale_item_id": sale["items"][0]["id"], "quantity": 1}],
            "reason": "Customer changed mind",
            "restock": True,
            "refund_amount": "20.00",
            "refund_method": "cash",
        },
    )
    assert returned.status_code == 201, returned.text

    expense = client.post(
        "/api/expenses",
        json={"category": "travel", "description": "Auto fare", "amount": "30.00", "method": "cash"},
    )
    assert expense.status_code == 201, expense.text

    receipt = client.post(
        "/api/inventory/receipts",
        json={
            "payment_method": "cash",
            "items": [{"product_id": item["id"], "quantity": 10, "unit_cost": "12.00"}],
        },
    )
    assert receipt.status_code == 201, receipt.text

    summary = client.get("/api/reports/summary", params=range_today(today)).json()
    assert summary["sales_count"] == 1
    assert summary["gross_sales"] == "100.00"
    assert summary["returns_value"] == "20.00"
    assert summary["net_sales"] == "80.00"
    assert summary["collected"] == "100.00"
    assert summary["refunds"] == "20.00"
    assert summary["ordinary_expenses"] == "30.00"
    assert summary["stock_purchases"] == "120.00"
    assert summary["total_expenses"] == "150.00"
    assert summary["outstanding"] == "0.00"
    assert summary["cash_in"] == "100.00"
    assert summary["cash_out"] == "170.00"
    assert summary["money_in"] == "100.00"
    assert summary["money_out"] == "170.00"
    assert "gross_profit" not in summary
    assert "net_profit" not in summary
    assert "cogs" not in summary
    assert "gross_margin_percent" not in summary

    top = summary["top_products"][0]
    assert top["quantity"] == 4
    assert top["revenue"] == "80.00"
    assert "cost" not in top
    assert "profit" not in top

    categories = {row["category"]: row for row in summary["expense_categories"]}
    assert categories["inventory_purchase"]["label"] == "Stock purchase"
    assert categories["inventory_purchase"]["amount"] == "120.00"
    assert categories["travel"]["amount"] == "30.00"

    methods = {row["method"]: row for row in summary["payment_methods"]}
    assert methods["cash"]["inflow"] == "100.00"
    assert methods["cash"]["outflow"] == "20.00"
    assert methods["cash"]["net"] == "80.00"

    day = summary["daily"][0]
    assert day["net_sales"] == "80.00"
    assert day["ordinary_expenses"] == "30.00"
    assert day["stock_purchases"] == "120.00"


def test_manual_stock_purchase_expense_requires_inventory_receipt(client):
    response = client.post(
        "/api/expenses",
        json={
            "category": "inventory_purchase",
            "description": "Chips stock bought at wholesale market",
            "amount": "500.00",
            "method": "cash",
        },
    )
    assert response.status_code == 422, response.text
    assert "Receive stock" in response.text

    ordinary = client.post(
        "/api/expenses",
        json={"category": "travel", "description": "Auto fare", "amount": "30.00", "method": "cash"},
    )
    assert ordinary.status_code == 201, ordinary.text
    assert ordinary.json()["kind"] == "ordinary"


def test_unpaid_sale_keeps_outstanding_out_of_money_received(client, product):
    item = product(price="40.00", cost="20.00", stock=30)
    unpaid = client.post("/api/sales", json={"items": [{"product_id": item["id"], "quantity": 2}]}).json()
    assert unpaid["payment_status"] == "unpaid"
    assert unpaid["outstanding"] == "80.00"
    assert unpaid["amount_paid"] == "0.00"

    dashboard = client.get("/api/dashboard", params={"range": "today"}).json()
    assert dashboard["summary"]["gross_sales"] == "80.00"
    assert dashboard["summary"]["outstanding"] == "80.00"
    assert dashboard["summary"]["collected"] == "0.00"
    assert dashboard["money_received"] == "0.00"
    assert dashboard["sale_payments_received"] == "0.00"
    assert dashboard["other_money_received"] == "0.00"
    assert dashboard["outstanding_total"] == "80.00"
    assert len(dashboard["pending_payments"]) == 1
    assert dashboard["pending_payments"][0]["outstanding"] == "80.00"
    assert dashboard["balance_complete"] is False
    assert "stock_value" not in dashboard
    assert "recent_sales" not in dashboard
    assert 1 <= len(dashboard["recent_activity"]) <= 5


def test_cash_and_upi_running_balances_ignore_the_other_method(client, product, today):
    set_settings(
        client,
        opening_cash_balance="100.00",
        opening_upi_balance="50.00",
        opening_balance_date=today.isoformat(),
    )
    item = product(price="100.00", cost="40.00", stock=20)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payment": {"amount": "200.00", "method": "cash"},
        },
    ).json()
    client.post(
        f"/api/sales/{sale['id']}/returns",
        json={
            "items": [{"sale_item_id": sale["items"][0]["id"], "quantity": 1}],
            "reason": "One returned",
            "restock": True,
            "refund_amount": "100.00",
            "refund_method": "cash",
        },
    )
    client.post("/api/expenses", json={"category": "travel", "description": "Fuel", "amount": "30.00", "method": "cash"})
    client.post("/api/handovers", json={"amount": "50.00", "method": "cash", "recipient": "Owner"})

    second = product(name="Sweet", price="50.00", cost="20.00", stock=10)
    client.post(
        "/api/sales",
        json={
            "items": [{"product_id": second["id"], "quantity": 1}],
            "initial_payment": {"amount": "50.00", "method": "upi"},
        },
    )

    money = client.get("/api/money/summary", params={"range": "today"}).json()
    assert money["opening_cash"] == "100.00"
    assert money["opening_upi"] == "50.00"
    assert money["cash_in"] == "200.00"
    assert money["upi_in"] == "50.00"
    assert money["cash_out"] == "180.00"
    assert money["upi_out"] == "0.00"
    assert money["current_cash"] == "120.00"
    assert money["current_upi"] == "100.00"
    assert money["balance_complete"] is True
    assert money["ordinary_expenses"] == "30.00"

    # The handover reduces cash but is not an ordinary expense.
    expenses = client.get("/api/expenses").json()
    assert expenses["total"] == 1
    assert money["closing_cash"] == "120.00"

    dashboard = client.get("/api/dashboard", params={"range": "today"}).json()
    assert dashboard["cash_available"] == "120.00"
    assert dashboard["upi_available"] == "100.00"
    assert dashboard["money_received"] == "250.00"
    assert dashboard["sale_payments_received"] == "250.00"
    assert dashboard["other_money_received"] == "0.00"


def test_expense_validation_void_and_stock_purchase_linkage(client, product):
    invalid_category = client.post(
        "/api/expenses",
        json={"category": "rent", "description": "Shop rent", "amount": "100.00", "method": "cash"},
    )
    assert invalid_category.status_code == 422
    invalid_method = client.post(
        "/api/expenses",
        json={"category": "miscellaneous", "description": "Other", "amount": "100.00", "method": "card"},
    )
    assert invalid_method.status_code == 422

    expense = client.post(
        "/api/expenses",
        json={"category": "miscellaneous", "description": "Cleaning", "amount": "25.00", "method": "cash"},
    ).json()
    voided = client.post(f"/api/expenses/{expense['id']}/void", json={"version": expense["version"], "reason": "Duplicate entry"})
    assert voided.status_code == 200
    assert voided.json()["is_void"] is True

    assert client.get("/api/expenses").json()["total"] == 0
    assert client.get("/api/expenses", params={"include_void": True}).json()["total"] == 1

    item = product(cost="8.00", price="15.00", stock=5)
    receipt = client.post(
        "/api/inventory/receipts",
        json={
            "supplier_ref": "SUP-11",
            "payment_method": "cash",
            "items": [{"product_id": item["id"], "quantity": 20, "unit_cost": "8.00"}],
        },
    )
    assert receipt.status_code == 201, receipt.text
    receipt_data = receipt.json()
    assert receipt_data["expense_id"]

    stock_rows = client.get("/api/expenses").json()
    assert stock_rows["total"] == 1
    row = stock_rows["items"][0]
    assert row["kind"] == "stock_purchase"
    assert row["linked_receipt_id"] == receipt_data["id"]
    assert row["amount"] == "160.00"

    money = client.get("/api/money/summary", params={"range": "all"}).json()
    assert money["ordinary_expenses"] == "0.00"
    assert money["stock_purchases"] == "160.00"
    assert money["money_out"] == "160.00"


def test_monthly_summary_and_dashboard_have_no_profit_fields(client, product, today):
    item = product(price="30.00", stock=10)
    client.post(
        "/api/sales",
        json={"items": [{"product_id": item["id"], "quantity": 1}], "initial_payment": {"amount": "30.00", "method": "cash"}},
    )
    monthly = client.get("/api/reports/monthly", params={"year": today.year}).json()
    current = monthly["months"][today.month - 1]
    assert current["month"] == today.month
    assert current["net_sales"] == "30.00"
    assert current["collected"] == "30.00"
    assert "net_profit" not in current
    assert "gross_profit" not in current

    dashboard = client.get("/api/dashboard", params={"range": "today"}).json()
    assert dashboard["summary"]["gross_sales"] == "30.00"
    assert dashboard["money_received"] == "30.00"
    assert dashboard["ordinary_expenses"] == "0.00"
    assert dashboard["cash_available"] == "30.00"
    assert dashboard["low_stock_count"] == 0
    assert dashboard["pending_payments"] == []
    assert len(dashboard["recent_activity"]) <= 5
    assert dashboard["low_stock_products"] == []


def test_sale_accepts_multiple_initial_payments(client, product):
    item = product(price="50.00", stock=10)
    response = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payments": [
                {"amount": "60.00", "method": "cash"},
                {"amount": "40.00", "method": "upi"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    sale = response.json()
    assert sale["total"] == "100.00"
    assert sale["amount_paid"] == "100.00"
    assert sale["payment_status"] == "paid"
    assert len(sale["payments"]) == 2
    assert {payment["method"] for payment in sale["payments"]} == {"cash", "upi"}

    overpaid = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payments": [
                {"amount": "40.00", "method": "cash"},
                {"amount": "20.00", "method": "upi"},
            ],
        },
    )
    assert overpaid.status_code == 422


def test_settings_replace_lists_and_validate_opening_balances(client, today):
    saved = set_settings(
        client,
        payment_methods=["upi", "card"],
        expense_categories=["travel", "food"],
        money_in_categories=["money_from_owner", "other_money_received"],
        money_out_categories=["money_to_owner", "expense_payment"],
        default_low_stock_threshold=7,
        opening_cash_balance="500.00",
        opening_upi_balance="250.00",
        opening_balance_date=today.isoformat(),
    )
    assert saved["payment_methods"][0] == "cash"
    assert set(saved["payment_methods"]) == {"cash", "upi", "card"}
    assert "inventory_purchase" in saved["expense_categories"]
    assert set(saved["expense_categories"]) == {"inventory_purchase", "travel", "food"}
    assert saved["money_in_categories"] == ["money_from_owner", "other_money_received"]
    assert saved["money_out_categories"] == ["money_to_owner", "expense_payment"]
    assert saved["default_low_stock_threshold"] == 7
    assert saved["opening_cash_balance"] == "500.00"
    assert saved["opening_upi_balance"] == "250.00"
    assert saved["opening_balance_date"] == today.isoformat()

    preserved = set_settings(client, business_name="Updated Cart")
    assert preserved["business_name"] == "Updated Cart"
    assert preserved["opening_cash_balance"] == "500.00"
    assert preserved["opening_upi_balance"] == "250.00"
    assert preserved["opening_balance_date"] == today.isoformat()

    missing_date = client.put(
        "/api/settings",
        json={
            "business_name": "Bad opening",
            "payment_methods": ["cash"],
            "expense_categories": ["travel"],
            "money_in_categories": ["other_money_received"],
            "money_out_categories": ["other_money_given"],
            "opening_cash_balance": "100.00",
            "opening_upi_balance": None,
            "opening_balance_date": None,
        },
    )
    assert missing_date.status_code == 422

    cleared = set_settings(client, clear_opening_balances=True)
    assert cleared["opening_cash_balance"] is None
    assert cleared["opening_upi_balance"] is None
    assert cleared["opening_balance_date"] is None
