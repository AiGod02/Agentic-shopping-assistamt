"""Alembic environment configuration for async PostgreSQL migrations."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import os
import sys
import pathlib

# Ensure project paths are in sys.path
project_root = pathlib.Path(__file__).resolve().parent.parent
for p in [str(project_root), str(project_root / "merchant_server"), str(project_root / "shared")]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from merchant_server.domain.models.base import Base
    import merchant_server.domain.models  # noqa: F401
    target_metadata = Base.metadata
except Exception:
    target_metadata = None


def get_url() -> str:
    from shared.db.session import normalize_database_url
    url = os.getenv("DATABASE_URL")
    if not url:
        url = config.get_main_option("sqlalchemy.url", "")
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    url = get_url()
    from shared.db.session import ensure_database_exists
    await ensure_database_exists(url)

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
