from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app import accounts as accounts_module
from app import security, userdata
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.utils import local_day, utcnow


@pytest.fixture(autouse=True)
def isolate_account_state(tmp_path: Path, monkeypatch):
    """Keep every test away from the real accounts database and user files."""
    monkeypatch.setattr(settings, "accounts_db_path", tmp_path / "accounts.db")
    monkeypatch.setattr(settings, "users_data_dir", tmp_path / "user_data")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    monkeypatch.setattr(settings, "password_iterations", 1000)
    monkeypatch.setattr(settings, "secret_key", "")
    accounts_module.reset_state()
    userdata.reset_state()
    security.reset_rate_limits()
    yield
    accounts_module.reset_state()
    userdata.reset_state()
    security.reset_rate_limits()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cartflow-test.db"


@pytest.fixture()
def session_factory(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        connection.execute(text("INSERT OR IGNORE INTO alembic_version (version_num) VALUES ('test')"))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()


@pytest.fixture()
def product(client):
    def make(
        *,
        name: str = "Test Chips",
        price: str = "20.00",
        cost: str = "12.00",
        stock: int = 50,
        low: int = 5,
        sku: str | None = None,
    ) -> dict:
        payload = {
            "name": name,
            "category": "Snacks",
            "purchase_cost": cost,
            "selling_price": price,
            "opening_stock": stock,
            "low_stock_threshold": low,
        }
        if sku:
            payload["sku"] = sku
        response = client.post("/api/products", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return make


@pytest.fixture()
def today() -> date:
    return local_day(utcnow())


def create_sale(client: TestClient, product: dict, **overrides) -> dict:
    payload = {
        "items": [{"product_id": product["id"], "quantity": 2}],
        "initial_payment": {"amount": "40.00", "method": "cash"},
    }
    payload.update(overrides)
    response = client.post("/api/sales", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def utc_iso(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> str:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).isoformat()
