"""
Standalone database initialization script.

Ensures the database exists (creating it if necessary in PostgreSQL/SQLite)
and creates all schema tables if they do not exist.
Optionally seeds default data if --seed flag is passed.

Usage:
    python init_db.py
    python init_db.py --seed
"""

import sys
import os
import asyncio
import argparse
import pathlib

# Ensure workspace paths are in sys.path
project_root = pathlib.Path(__file__).resolve().parent
for p in [str(project_root), str(project_root / "merchant_server"), str(project_root / "agent_server"), str(project_root / "payment_server"), str(project_root / "shared")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Load .env if present
try:
    from dotenv import load_dotenv
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
except ImportError:
    pass

from shared.db.session import (
    ensure_db_and_tables,
    ensure_database_exists,
    init_db_engine,
    init_db_tables,
    normalize_database_url,
    get_engine,
)


async def main(seed: bool = False):
    print("=" * 60)
    print(" Agentic Commerce Protocol — Database Initializer")
    print("=" * 60)

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/agenticcommerce"
    )
    db_url = normalize_database_url(db_url)
    display_url = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"[*] Target database: {display_url}")

    print("[*] Checking / creating database if missing...")
    await ensure_database_exists(db_url)
    print(" -> Database verified or created.")

    print("[*] Checking / creating database tables...")
    engine = init_db_engine(db_url)
    await init_db_tables(engine)
    print(" -> Schema tables verified or created.")

    if seed:
        print("[*] Seeding default database data...")
        try:
            from seed_db import seed as run_seed
            await run_seed()
            print(" -> Seeding completed successfully.")
        except Exception as seed_err:
            print(f" [!] Seeding error: {seed_err}")

    print("=" * 60)
    print(" Database and tables are ready for deployment! ")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize database and schema tables.")
    parser.add_argument("--seed", action="store_true", help="Also seed default mock data.")
    args = parser.parse_args()

    asyncio.run(main(seed=args.seed))
