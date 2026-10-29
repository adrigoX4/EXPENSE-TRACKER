"""Account storage for multi-user mode.

Accounts live in a small dedicated SQLite database. Each account points at its
own business database file, so sales, expenses and backups are isolated by
construction instead of relying on a filter in every query.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, String, create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings
from app.utils import utcnow


class AccountBase(DeclarativeBase):
    pass


class Account(AccountBase):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    data_file: Mapped[str] = mapped_column(String(500), nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AccountMeta(AccountBase):
    __tablename__ = "account_meta"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)


@dataclass(frozen=True)
class AccountUser:
    id: str
    email: str
    data_file: str
    is_owner: bool
    created_at: datetime


_lock = threading.RLock()
_engine: Engine | None = None
_engine_key: str | None = None
_schema_ready = False
_secret: str | None = None


def accounts_path() -> Path:
    return Path(settings.accounts_db_path).expanduser()


def _current_engine() -> Engine:
    global _engine, _engine_key, _schema_ready
    path = accounts_path().resolve()
    key = str(path)
    with _lock:
        if _engine is not None and _engine_key == key:
            return _engine
        if _engine is not None:
            _engine.dispose()
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 15},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _pragmas(connection, _record):  # noqa: ANN001
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

        _engine = engine
        _engine_key = key
        _schema_ready = False
        return engine


def ensure_schema() -> Engine:
    global _schema_ready
    engine = _current_engine()
    with _lock:
        if not _schema_ready:
            AccountBase.metadata.create_all(engine)
            _schema_ready = True
    return engine


def _session() -> Session:
    return sessionmaker(bind=ensure_schema(), autoflush=False, expire_on_commit=False)()


def reset_state() -> None:
    """Drop cached engines and secrets. Used by tests after settings change."""
    global _engine, _engine_key, _schema_ready, _secret
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_key = None
        _schema_ready = False
        _secret = None


def accounts_exist() -> bool:
    path = accounts_path()
    if not path.exists() or path.stat().st_size == 0:
        return False
    db = _session()
    try:
        return (db.scalar(select(func.count(Account.id))) or 0) > 0
    finally:
        db.close()


def _snapshot(row: Account) -> AccountUser:
    return AccountUser(
        id=row.id,
        email=row.email,
        data_file=row.data_file,
        is_owner=row.is_owner,
        created_at=row.created_at,
    )


def get_account(account_id: str) -> AccountUser | None:
    if not account_id or not accounts_path().exists():
        return None
    db = _session()
    try:
        row = db.get(Account, account_id)
        return _snapshot(row) if row else None
    finally:
        db.close()


def get_account_by_email(email: str) -> AccountUser | None:
    if not accounts_path().exists():
        return None
    db = _session()
    try:
        row = db.scalar(select(Account).where(Account.email == email.strip().lower()))
        return _snapshot(row) if row else None
    finally:
        db.close()


def get_password_hash(email: str) -> str | None:
    if not accounts_path().exists():
        return None
    db = _session()
    try:
        return db.scalar(select(Account.password_hash).where(Account.email == email.strip().lower()))
    finally:
        db.close()


def create_account(
    *,
    account_id: str,
    email: str,
    password_hash: str,
    data_file: str,
    is_owner: bool,
) -> AccountUser:
    db = _session()
    try:
        row = Account(
            id=account_id,
            email=email.strip().lower(),
            password_hash=password_hash,
            data_file=data_file,
            is_owner=is_owner,
            created_at=utcnow(),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError("An account with this email already exists") from exc
        return _snapshot(row)
    finally:
        db.close()


def touch_login(account_id: str) -> None:
    db = _session()
    try:
        row = db.get(Account, account_id)
        if row:
            row.last_login_at = utcnow()
            db.commit()
    finally:
        db.close()


def get_or_create_secret() -> str:
    """Session signing secret, shared by every process using the accounts DB."""
    global _secret
    configured = settings.secret_key.strip()
    if configured:
        return configured
    with _lock:
        if _secret:
            return _secret
        engine = ensure_schema()
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        db = factory()
        try:
            row = db.get(AccountMeta, "session_secret")
            if row is None:
                import secrets

                row = AccountMeta(key="session_secret", value=secrets.token_urlsafe(48))
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    row = db.get(AccountMeta, "session_secret")
            _secret = row.value if row else ""
            return _secret
        finally:
            db.close()
