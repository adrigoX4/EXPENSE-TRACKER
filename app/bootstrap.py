"""Initialize the database schema, optionally installing demonstration products."""

from __future__ import annotations

import argparse

from alembic import command
from alembic.config import Config

from app.config import BASE_DIR, settings


def upgrade() -> None:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize College Cart Personal Manager")
    parser.add_argument("--seed", action="store_true", help="Add clearly fictional demonstration products")
    args = parser.parse_args()

    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    upgrade()
    print(f"Database ready: {settings.database_url}")

    if args.seed:
        from app.seed import seed_products

        created = seed_products()
        print(f"Seeded {created} demonstration products." if created else "Seed skipped: products already exist.")


if __name__ == "__main__":
    main()
