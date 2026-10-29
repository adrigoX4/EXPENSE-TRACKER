from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_prefix="CARTFLOW_",
        extra="ignore",
    )

    app_name: str = "College Cart Personal Manager"
    database_url: str = f"sqlite:///{(BASE_DIR / 'college_cart.db').as_posix()}"
    accounts_db_path: Path = BASE_DIR / "accounts.db"
    users_data_dir: Path = BASE_DIR / "user_data"
    secret_key: str = ""
    session_days: int = 30
    allow_signup: bool = True
    password_iterations: int = 600_000
    cookie_secure: bool = False
    business_timezone: str = "Asia/Kolkata"
    dev_cors: bool = False
    frontend_dir: Path = BASE_DIR / "frontend"
    backups_dir: Path = BASE_DIR / "backups"
    uploads_dir: Path = BASE_DIR / "uploads"
    public_base_url: str = ""
    allow_indexing: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
