"""
SQLAlchemy Async Session — connection pooling and session management.

Provides the async engine, session factory, and dependency injection for FastAPI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from shared.observability.logging import get_logger

logger = get_logger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


import os
import sys
import pathlib
from urllib.parse import urlsplit, parse_qs

_tables_initialized: bool = False


def normalize_database_url(url: str) -> str:
    """Normalize database URL for async SQLAlchemy.
    Converts postgresql:// -> postgresql+asyncpg://
    Converts sqlite:/// -> sqlite+aiosqlite:///
    Cleans up any accidental prefixes or quotes.
    """
    if not url:
        return ""
    url = url.strip().strip("'\"")
    if "DATABASE_URL=" in url:
        url = url.split("DATABASE_URL=")[-1].strip()

    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]

    return url


def init_db_engine(
    database_url: str,
    pool_size: int = 20,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
    echo: bool = False,
):
    """Initialize the SQLAlchemy async engine.

    Supports both PostgreSQL (asyncpg) and SQLite (aiosqlite).
    For SQLite, connection pooling is disabled (StaticPool).
    """
    global _engine, _session_factory

    clean_url = normalize_database_url(database_url)

    engine_kwargs: dict = {
        "pool_pre_ping": True,
        "echo": echo,
    }

    if "sqlite" in clean_url:
        from sqlalchemy.pool import StaticPool
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["poolclass"] = AsyncAdaptedQueuePool
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_timeout"] = pool_timeout
        engine_kwargs["pool_recycle"] = pool_recycle

    _engine = create_async_engine(clean_url, **engine_kwargs)

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("db_engine_initialized", url=clean_url.split("@")[-1] if "@" in clean_url else clean_url)
    return _engine


def get_engine():
    """Get the current SQLAlchemy engine."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db_engine first.")
    return _engine


async def close_db_engine() -> None:
    """Dispose the engine and close all connections."""
    global _engine, _session_factory, _tables_initialized
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        _tables_initialized = False
        logger.info("db_engine_closed")


async def ensure_database_exists(database_url: str | None = None) -> bool:
    """Ensure the target database exists on the database server.
    If the target database does not exist (PostgreSQL), connects to the default
    maintenance database ('postgres' or 'template1') and executes CREATE DATABASE.
    For SQLite, creates parent directories if needed.
    """
    if not database_url:
        database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return True

    clean_url = normalize_database_url(database_url)

    if "sqlite" in clean_url:
        parsed = urlsplit(clean_url)
        db_path = parsed.path
        if db_path and db_path != ":memory:":
            if db_path.startswith("/") and len(db_path) > 2 and db_path[2] == ":":
                db_path = db_path[1:]
            parent_dir = os.path.dirname(os.path.abspath(db_path))
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
                logger.info("sqlite_dir_created", dir=parent_dir)
        return True

    if "postgres" in clean_url:
        parsed = urlsplit(clean_url)
        raw_path = parsed.path.lstrip("/")
        db_name = raw_path.split("?")[0] if "?" in raw_path else raw_path
        if not db_name or db_name in ("postgres", "template1"):
            return True

        ssl_mode = None
        query_params = parse_qs(parsed.query)
        if "ssl" in query_params or "sslmode" in query_params:
            ssl_mode = "require"

        # 1. Probe direct connection
        try:
            import asyncpg
            conn = await asyncpg.connect(
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                user=parsed.username or "postgres",
                password=parsed.password or None,
                database=db_name,
                ssl=ssl_mode,
                timeout=5.0,
            )
            await conn.close()
            logger.info("database_already_exists", database=db_name)
            return True
        except Exception as probe_err:
            err_str = str(probe_err).lower()
            logger.info("database_not_connected_probing_maintenance", database=db_name, note=err_str)

        # 2. Connect to maintenance DB and create if missing
        for maint_db in ["postgres", "template1"]:
            try:
                import asyncpg
                conn = await asyncpg.connect(
                    host=parsed.hostname or "localhost",
                    port=parsed.port or 5432,
                    user=parsed.username or "postgres",
                    password=parsed.password or None,
                    database=maint_db,
                    ssl=ssl_mode,
                    timeout=10.0,
                )
                try:
                    exists = await conn.fetchval(
                        "SELECT 1 FROM pg_database WHERE datname = $1", db_name
                    )
                    if not exists:
                        clean_db_name = db_name.replace('"', '""')
                        await conn.execute(f'CREATE DATABASE "{clean_db_name}"')
                        logger.info("database_created_successfully", database=db_name)
                    else:
                        logger.info("database_exists_in_catalog", database=db_name)
                    return True
                finally:
                    await conn.close()
            except Exception as maint_err:
                logger.warning("maintenance_db_attempt_failed", maint_db=maint_db, error=str(maint_err))

    return True


async def init_db_tables(engine=None) -> None:
    """Create all database tables asynchronously if they do not exist.
    Also ensures domain models are dynamically imported from sys.path
    and stamps alembic_version table to prevent migration collisions.
    """
    global _engine
    target_engine = engine or _engine
    if not target_engine:
        return

    # Add project paths to sys.path so merchant_server can be imported anywhere
    curr_path = pathlib.Path(__file__).resolve()
    # shared/shared/db/session.py -> 3 levels up is project root
    project_root = curr_path.parent.parent.parent
    for p in [
        str(project_root),
        str(project_root / "merchant_server"),
        str(project_root / "agent_server"),
        str(project_root / "payment_server"),
        str(pathlib.Path.cwd()),
        str(pathlib.Path.cwd() / "merchant_server"),
    ]:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    try:
        from merchant_server.domain.models.base import Base
        import merchant_server.domain.models  # noqa: F401

        async with target_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            # Auto-stamp alembic version if missing
            try:
                from sqlalchemy import text
                is_sqlite = "sqlite" in str(target_engine.url)
                if not is_sqlite:
                    res = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
                    tbl_exists = res.scalar()
                else:
                    res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"))
                    tbl_exists = res.scalar()

                if not tbl_exists:
                    await conn.execute(text(
                        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                    ))
                    await conn.execute(text(
                        "INSERT INTO alembic_version (version_num) VALUES ('008')"
                    ))
                    logger.info("alembic_version_stamped_to_head", version="008")
            except Exception as alembic_err:
                logger.debug("alembic_stamp_skipped", error=str(alembic_err))

        logger.info("db_tables_auto_created_or_verified")
    except Exception as e:
        logger.warning("db_tables_auto_creation_failed", error=str(e))


async def ensure_db_and_tables(database_url: str | None = None, engine=None) -> None:
    """Unified helper: ensures the database exists, engine is initialized,
    and all schema tables exist.
    """
    global _engine, _tables_initialized
    if _tables_initialized and (_engine is not None or engine is not None):
        return

    if not database_url:
        try:
            from agent_server.config import settings
            database_url = settings.database_url
        except Exception:
            try:
                from merchant_server.config import settings
                database_url = settings.database_url
            except Exception:
                database_url = os.getenv(
                    "DATABASE_URL",
                    "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/agenticcommerce"
                )

    await ensure_database_exists(database_url)

    target_engine = engine or _engine
    if target_engine is None:
        target_engine = init_db_engine(database_url)

    await init_db_tables(target_engine)
    _tables_initialized = True


from contextvars import ContextVar
from sqlalchemy import text

current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(query)
    """
    global _session_factory
    if _session_factory is None:
        import os
        try:
            from agent_server.config import settings
            db_url = settings.database_url
        except Exception:
            db_url = os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://commerce:commerce_secret@localhost:5432/commerce_platform"
            )
        init_db_engine(db_url)

    session = _session_factory()
    try:
        tenant_id = current_tenant_id.get(None)
        if tenant_id:
            # check if sqlite is used
            bind = session.bind
            is_sqlite = bind and "sqlite" in str(bind.url)
            if not is_sqlite:
                await session.execute(
                    text("SELECT set_config('app.current_merchant_id', :tid, true)"),
                    {"tid": str(tenant_id)}
                )
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.

    Usage:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_db_session() as session:
        yield session
