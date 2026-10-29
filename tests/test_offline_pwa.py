from __future__ import annotations

import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

PAGES = {
    "dashboard",
    "new-sale",
    "sales",
    "sale-detail",
    "inventory",
    "expenses",
    "money-history",
    "reports",
    "settings",
}


def test_every_required_page_module_exists_and_follows_contract():
    for page in PAGES:
        path = FRONTEND / "js" / "pages" / f"{page}.js"
        assert path.exists(), f"missing page module {page}"
        source = path.read_text(encoding="utf-8")
        assert "export default" in source
        assert re.search(r"async render\s*\(", source), f"{page} must expose async render(view, ctx)"
        assert "import " in source


def test_index_shell_has_pwa_and_accessibility_entry_points():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in html
    assert 'rel="manifest"' in html
    assert 'id="view"' in html
    assert 'id="toast-root"' in html
    assert 'Skip to content' in html
    assert 'aria-label="Primary navigation"' in html
    assert 'aria-label="Mobile navigation"' in html
    assert "modal-root" in html


def test_manifest_is_valid_installable_metadata():
    manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith("/")
    assert manifest["name"] and manifest["short_name"]
    assert manifest["icons"]
    assert all(icon["src"].startswith("/") for icon in manifest["icons"])


def test_service_worker_precaches_shell_and_every_page():
    sw = (FRONTEND / "sw.js").read_text(encoding="utf-8")
    for page in PAGES:
        assert f"/js/pages/{page}.js" in sw, f"{page} is not precached for offline use"
    assert 'request.mode === "navigate"' in sw
    assert 'url.pathname.startsWith("/api/")' in sw
    assert 'return fallback' in sw or "fallbackUrl" in sw


def test_frontend_has_no_external_dependencies_or_analytics():
    offenders = []
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".html", ".css", ".js", ".webmanifest"}:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"https?://[^\s\"'<>)]+", text):
            url = match.group(0)
            if "127.0.0.1" in url or "localhost" in url:
                continue
            if url.startswith("http://www.w3.org") or url.startswith("https://www.w3.org"):
                continue
            if url.startswith("https://schema.org") or url.startswith("http://schema.org"):
                continue
            offenders.append(f"{path.relative_to(FRONTEND)}: {url}")
    assert offenders == [], f"unexpected external references: {offenders}"


def test_offline_sale_queue_uses_client_uuid_and_idempotency_key():
    sync_source = (FRONTEND / "js" / "sync.js").read_text(encoding="utf-8")
    api_source = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    store_source = (FRONTEND / "js" / "store.js").read_text(encoding="utf-8")
    assert "Idempotency-Key" in api_source
    assert "client_uuid" in sync_source
    assert "operation.id" in sync_source
    assert "queueOperation" in store_source
    assert "pendingOperations" in store_source
    assert "indexedDB" in (FRONTEND / "js" / "db.js").read_text(encoding="utf-8")


def test_offline_money_and_expense_queue_replay_uses_the_same_key(client):
    money_payload = {
        "direction": "in",
        "amount": "15.00",
        "person": "Owner",
        "category": "money_from_owner",
        "method": "cash",
        "description": "Offline money entry",
        "idempotency_key": "offline-money-1",
    }
    first = client.post("/api/money/transactions", json=money_payload)
    second = client.post("/api/money/transactions", json=money_payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert first.json()["id"] == second.json()["id"]
    ledger = client.get("/api/money/ledger", params={"range": "all"}).json()
    assert ledger["total"] == 1
    assert ledger["items"][0]["direction"] == "in"


def test_expense_idempotency_survives_retry(client):
    payload = {
        "category": "miscellaneous",
        "description": "Offline entry",
        "amount": "12.00",
        "method": "cash",
        "idempotency_key": "offline-expense-1",
    }
    first = client.post("/api/expenses", json=payload)
    second = client.post("/api/expenses", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get("/api/expenses").json()["total"] == 1


def test_sale_retry_is_safe_after_ambiguous_network_failure(client, product):
    item = product(stock=10)
    payload = {
        "items": [{"product_id": item["id"], "quantity": 1}],
        "client_uuid": "6f6f6f6f-aaaa-4bbb-8ccc-ddddeeeeffff",
        "idempotency_key": "offline-expense-and-sale-1",
    }
    first = client.post("/api/sales", json=payload, headers={"Idempotency-Key": "offline-sale-key-1"})
    assert first.status_code == 201
    for _ in range(3):
        retry = client.post("/api/sales", json=payload, headers={"Idempotency-Key": "offline-sale-key-1"})
        assert retry.status_code == 200

    sales = client.get("/api/sales").json()
    assert sales["total"] == 1
    assert client.get(f"/api/products/{item['id']}").json()["stock_quantity"] == 9
    operations = client.get("/api/sync/operations").json()
    assert operations["total"] == 1
    assert operations["items"][0]["attempts"] == 4
