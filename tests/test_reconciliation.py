from __future__ import annotations


def test_duplicate_candidates_are_flagged_never_merged(client, product, today):
    item = product(price="50.00", stock=20)
    first = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "50.00", "method": "cash"},
            "customer_ref": "Room 12",
        },
    ).json()
    second = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "50.00", "method": "cash"},
            "customer_ref": "Room 12",
        },
    ).json()

    candidates = client.get(
        "/api/reconciliation/candidates",
        params={"date_from": today.isoformat(), "date_to": today.isoformat()},
    ).json()
    assert len(candidates) == 1
    candidate = candidates[0]
    pair = {candidate["sale_a"]["id"], candidate["sale_b"]["id"]}
    assert pair == {first["id"], second["id"]}
    assert candidate["score"] >= 65
    assert "Same total" in candidate["reasons"]
    assert "Identical product mix" in candidate["reasons"]

    review = client.post(
        "/api/reconciliation/duplicates/review",
        json={
            "sale_a_id": first["id"],
            "sale_b_id": second["id"],
            "status": "confirmed_duplicate",
            "notes": "Looks like the same order entered twice",
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "confirmed_duplicate"

    detail_a = client.get(f"/api/sales/{first['id']}").json()
    detail_b = client.get(f"/api/sales/{second['id']}").json()
    assert detail_a["reconciliation_status"] == "potential_duplicate"
    assert detail_b["reconciliation_status"] == "potential_duplicate"
    assert detail_a["status"] == "completed"
    assert detail_b["status"] == "completed"
    assert detail_a["total"] == "50.00"
    assert detail_b["total"] == "50.00"

    remaining = client.get(
        "/api/reconciliation/candidates",
        params={"date_from": today.isoformat(), "date_to": today.isoformat()},
    ).json()
    assert remaining == []

    queue = client.get("/api/reconciliation/queue").json()
    assert queue["counts"]["potential_duplicate"] == 2
    assert len(queue["reviewed_pairs"]) == 1


def test_web_order_reconciliation_and_link(client, product):
    item = product(name="Website Chips", price="40.00", stock=20)
    web_sale = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "source": "website",
            "external_order_id": "CC-WEB-501",
            "initial_payment": {"amount": "40.00", "method": "upi"},
        },
    ).json()
    assert web_sale["reconciliation_status"] == "recorded"

    dashboard = client.get("/api/dashboard", params={"range": "today"}).json()
    assert dashboard["unverified_website_orders"] == 1

    wrong_version = client.patch(
        f"/api/reconciliation/sales/{web_sale['id']}",
        json={"status": "verified", "version": 99},
    )
    assert wrong_version.status_code == 409
    assert wrong_version.json()["error"]["code"] == "version_conflict"

    verified = client.patch(
        f"/api/reconciliation/sales/{web_sale['id']}",
        json={
            "status": "verified",
            "website_total": "40.00",
            "notes": "Matched on the website",
            "version": web_sale["version"],
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["reconciliation_status"] == "verified"
    assert client.get("/api/dashboard", params={"range": "today"}).json()["unverified_website_orders"] == 0

    records = client.get("/api/reconciliation/records", params={"sale_id": web_sale["id"]}).json()
    assert records[0]["status"] == "verified"
    assert records[0]["website_total"] == "40.00"

    manual = client.post(
        "/api/sales",
        json={
            "items": [{"product_id": item["id"], "quantity": 1}],
            "initial_payment": {"amount": "40.00", "method": "cash"},
        },
    ).json()
    linked = client.post(
        "/api/reconciliation/link",
        json={"sale_id": manual["id"], "external_order_id": "CC-WEB-777", "version": manual["version"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["external_order_id"] == "CC-WEB-777"
    assert linked.json()["reconciliation_status"] == "verified"

    duplicate_link = client.post(
        "/api/reconciliation/link",
        json={"sale_id": manual["id"], "external_order_id": "CC-WEB-501"},
    )
    assert duplicate_link.status_code == 409
    assert duplicate_link.json()["error"]["code"] == "duplicate_external_order_id"


def test_status_filter_and_dismissed_pair(client, product, today):
    item = product(price="25.00", stock=20)
    first = client.post("/api/sales", json={"items": [{"product_id": item["id"], "quantity": 1}]}).json()
    second = client.post("/api/sales", json={"items": [{"product_id": item["id"], "quantity": 1}]}).json()

    dismissed = client.post(
        "/api/reconciliation/duplicates/review",
        json={"sale_a_id": second["id"], "sale_b_id": first["id"], "status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["sale_a_id"] == first["id"]

    candidates = client.get(
        "/api/reconciliation/candidates",
        params={"date_from": today.isoformat(), "date_to": today.isoformat()},
    ).json()
    assert candidates == []

    detail = client.get(f"/api/sales/{first['id']}").json()
    assert detail["reconciliation_status"] == "recorded"

    needs_review = client.patch(
        f"/api/reconciliation/sales/{first['id']}",
        json={"status": "needs_review", "notes": "Check website manually"},
    )
    assert needs_review.status_code == 200
    queue = client.get("/api/reconciliation/queue", params={"status": "needs_review"}).json()
    assert queue["total"] == 1
    assert queue["items"][0]["id"] == first["id"]
