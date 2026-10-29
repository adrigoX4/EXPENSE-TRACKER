from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import accounts
from app.config import settings
from app.database import Base
from app.main import app
from app.models import Product

OWNER = {"email": "owner@example.com", "password": "cartflow123"}
SECOND = {"email": "helper@example.com", "password": "helper12345"}


@pytest.fixture()
def auth_client():
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


def register(client: TestClient, credentials: dict | None = None):
    return client.post("/api/auth/register", json=credentials or OWNER)


def seed_legacy_database() -> None:
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Product(
                name="Legacy Chips",
                category="Snacks",
                purchase_cost=Decimal("10.00"),
                selling_price=Decimal("20.00"),
                stock_quantity=7,
                low_stock_threshold=2,
            )
        )
        db.commit()
    engine.dispose()


def test_first_run_status_and_auth_pages(auth_client):
    status = auth_client.get("/api/auth/status").json()
    assert status == {"has_accounts": False, "allow_signup": True, "authenticated": False}

    for path, heading in (("/login", "Sign in"), ("/signup", "Create your account")):
        page = auth_client.get(path)
        assert page.status_code == 200, path
        assert heading in page.text
        assert "__CARTFLOW_" not in page.text

    signup = auth_client.get("/signup").text
    assert "keeps all records already on this" in signup
    assert "/js/auth.js" in signup

    script = (Path(__file__).resolve().parent.parent / "frontend" / "js" / "auth.js").read_text(encoding="utf-8")
    assert 'mode === "signup" ? "/api/auth/register" : "/api/auth/login"' in script


def test_first_account_claims_existing_records(auth_client):
    seed_legacy_database()

    response = register(auth_client)
    assert response.status_code == 201, response.text
    assert response.json()["email"] == OWNER["email"]
    assert response.json()["is_owner"] is True

    owner = accounts.get_account_by_email(OWNER["email"])
    assert owner is not None
    assert owner.data_file.replace("\\", "/").endswith("legacy.db")

    products = auth_client.get("/api/products").json()
    assert products["total"] == 1
    assert products["items"][0]["name"] == "Legacy Chips"


def test_second_account_starts_isolated(auth_client):
    seed_legacy_database()
    assert register(auth_client).status_code == 201

    created = auth_client.post(
        "/api/products",
        json={
            "name": "Owner Chips",
            "category": "Snacks",
            "purchase_cost": "10.00",
            "selling_price": "20.00",
            "opening_stock": 12,
            "low_stock_threshold": 3,
        },
    )
    assert created.status_code == 201, created.text
    auth_client.post(
        "/api/expenses",
        json={"category": "travel", "description": "Owner travel", "amount": "30.00", "method": "cash"},
    )
    owner_backup = auth_client.get("/api/backup/info").json()
    assert owner_backup["table_counts"]["products"] == 2
    assert owner_backup["table_counts"]["expenses"] == 1

    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/products").status_code == 401

    owner = accounts.get_account_by_email(OWNER["email"])
    assert owner is not None
    second = register(auth_client, SECOND)
    assert second.status_code == 201, second.text
    assert second.json()["is_owner"] is False
    helper = accounts.get_account_by_email(SECOND["email"])
    assert helper is not None
    assert "user_data" in helper.data_file.replace("\\", "/")
    assert helper.data_file != owner.data_file

    assert auth_client.get("/api/products").json()["total"] == 0
    assert auth_client.get("/api/expenses").json()["total"] == 0
    helper_backup = auth_client.get("/api/backup/info").json()
    assert helper_backup["table_counts"]["products"] == 0
    assert helper_backup["table_counts"]["expenses"] == 0

    settings_payload = auth_client.get("/api/settings").json()
    assert settings_payload["business_name"] == "College Cart"


def test_registration_validation_and_duplicates(auth_client):
    assert register(auth_client).status_code == 201
    duplicate = register(auth_client, {"email": "OWNER@example.com", "password": "another123"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_taken"

    bad_email = register(auth_client, {"email": "not-an-email", "password": "cartflow123"})
    assert bad_email.status_code == 422

    short = register(auth_client, {"email": "new@example.com", "password": "short1"})
    assert short.status_code == 422
    assert "8 characters" in short.json()["error"]["message"]

    no_digit = register(auth_client, {"email": "new@example.com", "password": "onlyletters"})
    assert no_digit.status_code == 422
    assert "letter and one number" in no_digit.json()["error"]["message"]


def test_login_logout_and_session_cookie(auth_client):
    register(auth_client)
    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/products").status_code == 401

    wrong = auth_client.post("/api/auth/login", json={"email": OWNER["email"], "password": "wrongpass1"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"

    unknown = auth_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpass1"})
    assert unknown.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    login = auth_client.post("/api/auth/login", json=OWNER)
    assert login.status_code == 200, login.text
    assert "cartflow_session" in auth_client.cookies
    me = auth_client.get("/api/auth/me").json()
    assert me["email"] == OWNER["email"]


def test_passwords_are_stored_hashed(auth_client):
    register(auth_client)
    stored = accounts.get_password_hash(OWNER["email"])
    assert stored is not None
    assert stored.startswith("pbkdf2_sha256$")
    assert OWNER["password"] not in stored


def test_tampered_session_cookie_is_rejected(auth_client):
    register(auth_client)
    token = auth_client.cookies.get("cartflow_session")
    assert token
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")

    fresh = TestClient(app)
    try:
        response = fresh.get("/api/products", headers={"Cookie": f"cartflow_session={tampered}"})
        assert response.status_code == 401
        page = fresh.get("/dashboard", headers={"Cookie": f"cartflow_session={tampered}"}, follow_redirects=False)
        assert page.status_code == 303
        assert page.headers["location"].startswith("/login")
    finally:
        fresh.close()


def test_app_pages_redirect_and_show_account(auth_client):
    register(auth_client)

    html = auth_client.get("/dashboard")
    assert html.status_code == 200
    assert OWNER["email"] in html.text
    assert '"authenticated":true' in html.text
    assert 'id="account-card"' in html.text
    assert "Sign out" in html.text

    auth_client.post("/api/auth/logout")
    redirect = auth_client.get("/dashboard", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/login?next=/dashboard"

    login = auth_client.get("/login")
    assert login.status_code == 200


def test_unauthenticated_api_and_cross_site_requests_are_blocked(auth_client):
    register(auth_client)
    auth_client.post("/api/auth/logout")

    assert auth_client.get("/api/products").status_code == 401
    assert auth_client.get("/api/backup/info").status_code == 401
    assert auth_client.get("/api/health").status_code == 200
    assert auth_client.get("/api/health").json()["accounts"] is True

    cross_site = auth_client.post(
        "/api/auth/login",
        json=OWNER,
        headers={"Origin": "https://evil.example"},
    )
    assert cross_site.status_code == 403
    assert cross_site.json()["error"]["code"] == "cross_site_request"


def test_login_rate_limit(auth_client):
    register(auth_client)
    auth_client.post("/api/auth/logout")
    for _ in range(8):
        attempt = auth_client.post("/api/auth/login", json={"email": OWNER["email"], "password": "wrongpass1"})
        assert attempt.status_code == 401
    blocked = auth_client.post("/api/auth/login", json={"email": OWNER["email"], "password": "wrongpass1"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_signup_can_be_closed_after_the_first_account(auth_client, monkeypatch):
    register(auth_client)
    monkeypatch.setattr(settings, "allow_signup", False)

    status = auth_client.get("/api/auth/status").json()
    assert status["allow_signup"] is False
    assert status["authenticated"] is True

    closed = register(auth_client, {"email": "late@example.com", "password": "latecomer1"})
    assert closed.status_code == 403
    assert closed.json()["error"]["code"] == "signup_disabled"

    auth_client.post("/api/auth/logout")
    page = auth_client.get("/signup", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login"


def test_settings_and_backups_are_per_account(auth_client):
    register(auth_client)
    updated = auth_client.put(
        "/api/settings",
        json={
            "business_name": "Owner's Cart",
            "payment_methods": ["cash", "upi"],
            "expense_categories": ["inventory_purchase", "travel"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert auth_client.get("/api/settings").json()["business_name"] == "Owner's Cart"

    snapshot = auth_client.post("/api/backup/create").json()
    with sqlite3.connect(snapshot["path"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0

    auth_client.post("/api/auth/logout")
    register(auth_client, SECOND)
    assert auth_client.get("/api/settings").json()["business_name"] == "College Cart"

    helper = accounts.get_account_by_email(SECOND["email"])
    assert helper is not None
    assert helper.data_file.replace("\\", "/") not in snapshot["path"].replace("\\", "/")
