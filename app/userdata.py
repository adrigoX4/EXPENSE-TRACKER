"""Per-account SQLite databases.

Each account owns a separate database file. Requests resolve the file from the
signed-in account, so every existing query is naturally scoped to that user and
a missing filter cannot expose another account's records.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.accounts import AccountUser
from app.config import BASE_DIR, settings

_lock = threading.RLock()
_engines: dict[str, Engine] = {}


def default_database_path() -> Path:
    """Business database used before the first account and by command-line tools."""
    url = make_url(settings.database_url)
    raw = url.database or "college_cart.db"
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def resolve_data_file(account: AccountUser) -> Path:
    path = Path(account.data_file).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def new_data_file(account_id: str) -> Path:
    directory = Path(settings.users_data_dir).expanduser()
    if not directory.is_absolute():
        directory = BASE_DIR / directory
    directory.mkdir(parents=True, exist_ok=True)
    return (directory / f"user-{account_id}.db").resolve()


def engine_for(path: Path) -> Engine:
    key = str(path.resolve())
    with _lock:
        engine = _engines.get(key)
        if engine is not None:
            return engine
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
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

        _engines[key] = engine
        return engine


def session_for_path(path: Path) -> Session:
    return sessionmaker(bind=engine_for(path), autoflush=False, expire_on_commit=False)()


def dispose_path(path: Path) -> None:
    key = str(path.resolve())
    with _lock:
        engine = _engines.pop(key, None)
    if engine is not None:
        engine.dispose()


def reset_state() -> None:
    with _lock:
        engines = list(_engines.values())
        _engines.clear()
    for engine in engines:
        engine.dispose()


def run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _schema_present(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    engine = engine_for(path)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        ).fetchone()
        return row is not None


def ensure_user_database(path: Path) -> None:
    """Create or validate a user's database and install default settings."""
    from app.services.settings_service import ensure_defaults_installed

    path.parent.mkdir(parents=True, exist_ok=True)
    if not _schema_present(path):
        run_migrations(f"sqlite:///{path.as_posix()}")
    db = session_for_path(path)
    try:
        ensure_defaults_installed(db)
    finally:
        db.close()
