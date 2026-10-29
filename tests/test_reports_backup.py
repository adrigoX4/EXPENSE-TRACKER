from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import settings
from app.services.backup import backup_info, create_snapshot, validate_sqlite_file


def test_reports_summary_resolution_and_validation(client, product, today):
    item = product(price="20.00", stock=10)
    client.post(
        "/api/sales",
        json={"items": [{"product_id": item["id"], "quantity": 1}], "initial_payment": {"amount": "20.00", "method": "cash"}},
    )
    summary = client.get("/api/reports/summary", params={"range": "today"}).json()
    assert summary["date_from"] == today.isoformat()
    assert summary["date_to"] == today.isoformat()
    assert summary["gross_sales"] == "20.00"

    invalid = client.get(
        "/api/reports/summary",
        params={"range": "custom", "date_from": today.isoformat(), "date_to": "2000-01-01"},
    )
    assert invalid.status_code == 422
    assert "on or before" in invalid.json()["error"]["message"]

    monthly = client.get("/api/reports/monthly", params={"year": today.year}).json()
    assert monthly["year"] == today.year
    assert len(monthly["months"]) == today.month
    assert monthly["months"][-1]["month"] == today.month


def test_csv_exports_are_bom_prefixed_and_formula_safe(client, product):
    item = product(name="Chips", price="20.00", stock=5)
    client.post(
        "/api/sales",
        json={"items": [{"product_id": item["id"], "quantity": 1}], "initial_payment": {"amount": "20.00", "method": "cash"}},
    )
    client.post(
        "/api/expenses",
        json={
            "category": "miscellaneous",
            "description": "=SUM(1,1)",
            "amount": "5.00",
            "method": "cash",
            "notes": "@malicious",
        },
    )
    client.post(
        "/api/money/transactions",
        json={
            "direction": "in",
            "amount": "25.00",
            "person": "=Owner",
            "category": "money_from_owner",
            "method": "cash",
            "description": "Top-up +adjustment",
        },
    )

    sales = client.get("/api/reports/export", params={"type": "sales"})
    assert sales.status_code == 200
    assert sales.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in sales.headers["content-disposition"]
    sales_text = sales.content.decode("utf-8-sig")
    assert "Sale ID" in sales_text
    assert "Chips" in sales_text

    expenses = client.get("/api/reports/export", params={"type": "expenses"}).content.decode("utf-8-sig")
    assert "'=SUM(1,1)" in expenses
    assert "'@malicious" in expenses

    money = client.get("/api/reports/export", params={"type": "money"}).content.decode("utf-8-sig")
    assert "Entry type" in money
    assert "'=Owner" in money
    assert "Money received from owner" in money

    expected_headers = {
        "inventory": "Retail value",
        "payments": "Payment ID",
        "movements": "Movement ID",
        "money": "Entry type",
        "monthly": "Net sales",
    }
    for export_type, header in expected_headers.items():
        response = client.get("/api/reports/export", params={"type": export_type})
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert header in response.content.decode("utf-8-sig")

    daily = client.get(
        "/api/reports/export",
        params={"type": "daily", "date_from": "2026-01-01", "date_to": "2026-01-02"},
    )
    assert daily.status_code == 200
    missing_dates = client.get("/api/reports/export", params={"type": "daily"})
    assert missing_dates.status_code == 422

    unknown = client.get("/api/reports/export", params={"type": "mystery"})
    assert unknown.status_code == 422


def test_backup_snapshot_and_validation(client, product, db_path, tmp_path, monkeypatch):
    product(name="Snapshot Chips", stock=3)
    backups = tmp_path / "backups"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(settings, "backups_dir", backups)

    info = client.get("/api/backup/info").json()
    assert info["database_path"] == str(db_path)
    assert info["table_counts"]["products"] == 1
    assert info["size_bytes"] > 0

    created = client.post("/api/backup/create").json()
    snapshot = Path(created["path"])
    assert snapshot.exists()
    assert snapshot.parent == backups

    validation = validate_sqlite_file(snapshot)
    assert validation["integrity"] == "ok"
    assert validation["alembic_version"] == "test"
    assert "products" in validation["tables"]

    upload = client.post(
        "/api/backup/validate",
        files={"upload": ("snapshot.db", snapshot.read_bytes(), "application/x-sqlite3")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["integrity"] == "ok"

    refused = client.post(
        "/api/backup/restore?confirm=NO",
        files={"upload": ("snapshot.db", snapshot.read_bytes(), "application/x-sqlite3")},
    )
    assert refused.status_code == 422
    assert "REPLACE" in refused.json()["error"]["message"]


def test_backup_validation_rejects_incomplete_databases(client, tmp_path, db_path, monkeypatch, session_factory):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(settings, "backups_dir", tmp_path / "backups")

    incomplete = tmp_path / "incomplete.db"
    with sqlite3.connect(incomplete) as connection:
        connection.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        connection.commit()

    response = client.post(
        "/api/backup/validate",
        files={"upload": ("incomplete.db", incomplete.read_bytes(), "application/x-sqlite3")},
    )
    assert response.status_code == 422
    assert "missing required tables" in response.json()["error"]["message"]

    empty = client.post("/api/backup/validate", files={"upload": ("empty.db", b"", "application/x-sqlite3")})
    assert empty.status_code == 422

    assert backup_info(session_factory())["table_counts"]["products"] == 0


def test_settings_roundtrip_and_audit(client):
    default = client.get("/api/settings").json()
    assert default["payment_methods"][0] == "cash"
    assert "inventory_purchase" in default["expense_categories"]

    updated = client.put(
        "/api/settings",
        json={
            "business_name": "College Cart",
            "payment_methods": ["upi"],
            "expense_categories": ["delivery"],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["payment_methods"] == ["cash", "upi"]
    assert body["expense_categories"][0] == "inventory_purchase"
    assert "delivery" in body["expense_categories"]

    invalid = client.put(
        "/api/settings",
        json={"business_name": "  ", "payment_methods": ["cash"], "expense_categories": ["delivery"]},
    )
    assert invalid.status_code == 422

    audit = client.get("/api/audit", params={"entity_type": "settings"}).json()
    assert audit[0]["action"] == "updated"
    after = json.loads(audit[0]["after_json"])
    assert after["payment_methods"] == ["cash", "upi"]

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
