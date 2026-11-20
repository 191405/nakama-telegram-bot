"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import settings

import os
import shutil
from pathlib import Path

# Ensure directory exists for SQLite files (e.g., /data/filebot.db on Fly.io volume)
if settings.database_url.startswith("sqlite"):
    raw_path = settings.database_url.split(":///", 1)[-1]
    db_path = Path(raw_path)
    if db_path.parent and str(db_path.parent) != ".":
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    # If target database does not exist yet but a local seed filebot.db exists, copy it over
    try:
        if not db_path.exists() and Path("filebot.db").exists():
            if db_path.resolve() != Path("filebot.db").resolve():
                shutil.copy2("filebot.db", db_path)
    except Exception:
        pass

engine_kwargs: dict = {"echo": False}
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update({"pool_size": 20, "max_overflow": 10})

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

# Concurrency & Performance: Enable WAL mode and busy timeout for SQLite
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


logger = logging.getLogger(__name__)

# Forward-only, idempotent schema migrations. Each entry is
# (name, table, column, SQL). Applied versions are tracked in the database so
# failures are logged and never silently swallowed.
MIGRATIONS: list[tuple[str, str, str, str]] = [
    (
        "001_user_persona",
        "users",
        "persona",
        "ALTER TABLE users ADD COLUMN persona VARCHAR(50) DEFAULT 'nakama'",
    ),
    (
        "002_user_xp",
        "users",
        "xp",
        "ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0",
    ),
    (
        "003_file_channel_message_id",
        "files",
        "channel_message_id",
        "ALTER TABLE files ADD COLUMN channel_message_id BIGINT",
    ),
]


async def _applied_migrations(conn) -> set[str]:
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name VARCHAR(255) PRIMARY KEY, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    ))
    result = await conn.execute(text("SELECT name FROM schema_migrations"))
    return {row[0] for row in result.fetchall()}


async def _column_exists(conn, table: str, column: str) -> bool:
    if settings.database_url.startswith("sqlite"):
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        return column in {row[1] for row in result.fetchall()}
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.first() is not None


async def init_db() -> None:
    """Create tables and apply pending, versioned schema migrations."""
    from bot.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        applied = await _applied_migrations(conn)

        for name, table, column, ddl in MIGRATIONS:
            if name in applied:
                continue
            try:
                if await _column_exists(conn, table, column):
                    # Column predates migration tracking (older deployment):
                    # record it as already applied instead of duplicating it.
                    await conn.execute(
                        text("INSERT INTO schema_migrations(name) VALUES (:n)"),
                        {"n": name},
                    )
                    logger.info("Recorded existing column for migration %s", name)
                    continue

                await conn.execute(text(ddl))
                await conn.execute(
                    text("INSERT INTO schema_migrations(name) VALUES (:n)"),
                    {"n": name},
                )
                logger.info("Applied schema migration: %s", name)
            except Exception:
                logger.exception("Schema migration '%s' failed", name)
                raise


async def close_db() -> None:
    """Dispose the engine connection pool."""
    await engine.dispose()
