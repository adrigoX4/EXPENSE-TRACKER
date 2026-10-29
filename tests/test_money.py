from __future__ import annotations

from datetime import timedelta

from conftest import utc_iso


def configure_opening(client, today, *, cash="1000.00", upi="500.00"):
    response = client.put(
        "/api/settings",
        json={
            "business_name": "College Cart",
            "payment_methods": ["cash", "upi"],
            "expense_categories": ["inventory_purchase", "travel", "miscellaneous"],
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
            "opening_cash_balance": cash,
            "opening_upi_balance": upi,
            "opening_balance_date": today.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_money(client, **overrides):
    payload = {
        "direction": "in",
        "amount": "10.00",
        "category": "other_money_received",
        "method": "cash",
        "description": "Money entry",
    }
    payload.update(overrides)
    response = client.post("/api/money/transactions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def ledger(client, **params):
    response = client.get("/api/money/ledger", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_manual_money_entries_update_cash_and_upi_running_balances(client, today):
    configure_opening(client, today)
    add_money(
        client,
        amount="200.00",
        person="Shop owner",
        category="money_from_owner",
        occurred_at=utc_iso(today.year, today.month, today.day, 9, 30),
        description="Float from owner",
    )
    add_money(
        client,
        direction="out",
        amount="50.00",
        category="expense_payment",
        method="upi",
        occurred_at=utc_iso(today.year, today.month, today.day, 10, 0),
        description="Paid supplier by UPI",
    )
    add_money(
        client,
        amount="30.00",
        person="Riya",
        category="repayment_received",
        method="upi",
        occurred_at=utc_iso(today.year, today.month, today.day, 11, 0),
        description="Repayment received",
    )
    add_money(
        client,
        direction="out",
        amount="100.00",
        person="Shop owner",
        category="cash_handover",
        occurred_at=utc_iso(today.year, today.month, today.day, 12, 0),
        description="Cash handover",
    )

    data = ledger(client, range="today")
    assert data["total"] == 4
    assert data["summary"]["money_in"] == "230.00"
    assert data["summary"]["money_out"] == "150.00"
    assert data["summary"]["cash_in"] == "200.00"
    assert data["summary"]["cash_out"] == "100.00"
    assert data["summary"]["upi_in"] == "30.00"
    assert data["summary"]["upi_out"] == "50.00"
    assert data["summary"]["count"] == 4
    assert data["summary"]["opening_cash"] == "1000.00"
    assert data["summary"]["opening_upi"] == "500.00"
    assert data["summary"]["closing_cash"] == "1100.00"
    assert data["summary"]["closing_upi"] == "480.00"
    assert data["summary"]["current_cash"] == "1100.00"
    assert data["summary"]["current_upi"] == "480.00"
    assert data["summary"]["balance_complete"] is True

    latest = data["items"][0]
    assert latest["occurred_at"].startswith(f"{today.isoformat()}T12:00")
    assert latest["cash_balance_after"] == "1100.00"
    assert latest["upi_balance_after"] == "480.00"
    assert latest["direction"] == "out"
    assert latest["category_label"] == "Cash handover"

    incoming = ledger(client, range="today", direction="in")
    assert incoming["total"] == 2
    upi_only = ledger(client, range="today", method="upi")
    assert upi_only["total"] == 2
    owner = ledger(client, range="today", search="owner")
    assert owner["total"] == 2
    by_amount = ledger(client, range="today", search="200.00")
    assert by_amount["total"] == 1
    assert by_amount["items"][0]["amount"] == "200.00"
    category = ledger(client, range="today", category="repayment_received")
    assert category["total"] == 1

    yesterday = (today - timedelta(days=1)).isoformat()
    empty = ledger(client, range="custom", date_from=yesterday, date_to=yesterday)
    assert empty["total"] == 0
    assert empty["summary"]["money_in"] == "0.00"


def test_backdated_money_entry_keeps_creation_timestamp_and_balance_gap(client, today):
    configure_opening(client, today)
    yesterday = today - timedelta(days=1)
    entry = add_money(
        client,
        amount="75.00",
        person="Old dues",
        occurred_at=utc_iso(yesterday.year, yesterday.month, yesterday.day, 12, 0),
        description="Backdated repayment",
    )
    assert entry["occurred_at"].startswith(yesterday.isoformat())
    assert entry["created_at"] != entry["occurred_at"]

    data = ledger(client, range="all")
    assert data["total"] == 1
    row = data["items"][0]
    assert row["occurred_at"].startswith(yesterday.isoformat())
    assert row["cash_balance_after"] is None
    assert row["upi_balance_after"] is None
    assert data["summary"]["current_cash"] == "1000.00"


def test_money_correction_void_and_audit_trail(client, today):
    configure_opening(client, today)
    entry = add_money(client, amount="100.00", person="Riya", description="Initial entry")

    corrected = client.patch(
        f"/api/money/transactions/{entry['id']}",
        json={
            "version": entry["version"],
            "amount": "120.00",
            "person": "Riya Sharma",
            "description": "Corrected entry",
        },
    )
    assert corrected.status_code == 200, corrected.text
    corrected_data = corrected.json()
    assert corrected_data["amount"] == "120.00"
    assert corrected_data["version"] == entry["version"] + 1
    assert corrected_data["created_at"] == entry["created_at"]

    stale = client.patch(
        f"/api/money/transactions/{entry['id']}",
        json={"version": entry["version"], "amount": "130.00"},
    )
    assert stale.status_code == 409

    audit = client.get(
        "/api/audit",
        params={"entity_type": "money_transaction", "entity_id": str(entry["id"])},
    ).json()
    actions = {row["action"] for row in audit}
    assert {"created", "updated"} <= actions
    update_row = next(row for row in audit if row["action"] == "updated")
    assert '"100.00"' in (update_row["before_json"] or "")
    assert '"120.00"' in (update_row["after_json"] or "")

    wrong_version = client.post(
        f"/api/money/transactions/{entry['id']}/void",
        json={"version": entry["version"], "reason": "Duplicate"},
    )
    assert wrong_version.status_code == 409

    voided = client.post(
        f"/api/money/transactions/{entry['id']}/void",
        json={"version": corrected_data["version"], "reason": "Duplicate"},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["is_void"] is True
    assert voided.json()["void_reason"] == "Duplicate"

    hidden = ledger(client, range="all")
    assert hidden["total"] == 0
    assert hidden["summary"]["money_in"] == "0.00"
    with_void = ledger(client, range="all", include_void=True)
    assert with_void["total"] == 1
    assert with_void["items"][0]["is_void"] is True
    assert with_void["summary"]["money_in"] == "0.00"

    blocked = client.patch(
        f"/api/money/transactions/{entry['id']}",
        json={"version": voided.json()["version"], "description": "Should fail"},
    )
    assert blocked.status_code == 409


def test_handover_reduces_only_cash_and_is_not_an_expense(client, today):
    configure_opening(client, today, cash="500.00", upi="100.00")
    payload = {
        "direction": "out",
        "amount": "200.00",
        "person": "Owner",
        "category": "cash_handover",
        "method": "cash",
        "description": "Cash handed to owner",
        "idempotency_key": "handover-offline-1",
    }
    first = client.post("/api/money/transactions", json=payload)
    second = client.post("/api/money/transactions", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    summary = client.get("/api/money/summary", params={"range": "today"}).json()
    assert summary["cash_out"] == "200.00"
    assert summary["upi_out"] == "0.00"
    assert summary["current_cash"] == "300.00"
    assert summary["current_upi"] == "100.00"
    assert summary["ordinary_expenses"] == "0.00"
    assert summary["stock_purchases"] == "0.00"
    assert summary["money_out"] == "200.00"
    assert summary["count"] == 1

    assert client.get("/api/expenses").json()["total"] == 0
    assert "profit" not in summary


def test_cash_to_upi_transfer_moves_balances_without_inflating_totals(client, today):
    configure_opening(client, today, cash="500.00", upi="500.00")
    add_money(
        client,
        direction="out",
        amount="100.00",
        category="cash_upi_transfer",
        method="cash",
        description="Move cash to UPI",
    )

    summary = client.get("/api/money/summary", params={"range": "today"}).json()
    assert summary["current_cash"] == "400.00"
    assert summary["current_upi"] == "600.00"
    assert summary["money_in"] == "0.00"
    assert summary["money_out"] == "0.00"
    assert summary["cash_out"] == "100.00"
    assert summary["upi_in"] == "100.00"
    assert summary["ordinary_expenses"] == "0.00"
    assert summary["stock_purchases"] == "0.00"
    assert summary["count"] == 1
    assert "profit" not in summary

    entry = ledger(client, range="today")
    assert entry["total"] == 1
    transfer = entry["items"][0]
    assert transfer["category"] == "cash_upi_transfer"
    assert transfer["category_label"] == "Transfer between cash & UPI"
    assert transfer["money_id"] is not None

    blocked = client.post(
        "/api/money/transactions",
        json={
            "direction": "in",
            "amount": "10.00",
            "category": "cash_upi_transfer",
            "method": "upi",
            "description": "Invalid transfer direction",
        },
    )
    assert blocked.status_code == 422
    assert "recorded once" in blocked.text.lower()


def test_sale_expense_and_handover_appear_once_with_links(client, product, today):
    configure_opening(client, today, cash="0.00", upi="0.00")
    item = product(price="50.00", cost="20.00", stock=10)
    sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 2}],
            "initial_payment": {"amount": "100.00", "method": "cash"},
        },
    ).json()
    expense = client.post(
        "/api/expenses",
        json={"category": "travel", "description": "Auto fare", "amount": "20.00", "method": "cash"},
    ).json()
    add_money(
        client,
        direction="out",
        amount="30.00",
        person="Owner",
        category="cash_handover",
        method="cash",
        description="Handover to owner",
    )

    data = ledger(client, range="all")
    assert data["total"] == 3
    sources = sorted(row["source"] for row in data["items"])
    assert sources == ["expense", "money", "payment"]
    assert data["summary"]["money_in"] == "100.00"
    assert data["summary"]["money_out"] == "50.00"
    assert data["summary"]["sale_payments_in"] == "100.00"
    assert data["summary"]["other_money_in"] == "0.00"
    assert data["summary"]["ordinary_expenses"] == "20.00"
    assert data["summary"]["current_cash"] == "50.00"

    payment_row = next(row for row in data["items"] if row["source"] == "payment")
    assert payment_row["sale_id"] == sale["id"]
    assert payment_row["link"] == f"/sales/{sale['id']}"
    expense_row = next(row for row in data["items"] if row["source"] == "expense")
    assert expense_row["expense_id"] == expense["id"]
    assert expense_row["link"].startswith(f"/expenses?focus={expense['id']}")
    handover_row = next(row for row in data["items"] if row["source"] == "money")
    assert handover_row["person"] == "Owner"
    assert handover_row["category_label"] == "Cash handover"


def test_money_monthly_summary_matches_daily_totals(client, today):
    configure_opening(client, today)
    add_money(client, amount="40.00", description="Inflow")
    add_money(
        client,
        direction="out",
        amount="15.00",
        category="other_money_given",
        method="upi",
        description="Outflow",
    )
    monthly = client.get("/api/money/monthly", params={"year": today.year}).json()
    row = next(item for item in monthly["months"] if item["month"] == today.month)
    assert row["money_in"] == "40.00"
    assert row["money_out"] == "15.00"
    assert row["cash_in"] == "40.00"
    assert row["upi_out"] == "15.00"
    assert row["count"] == 2
