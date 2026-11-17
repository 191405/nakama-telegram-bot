"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

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


async def init_db() -> None:
    """Create all tables and perform safe schema migrations."""
    from bot.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe column addition for users and files tables
        try:
            if settings.database_url.startswith("sqlite"):
                cols_res = await conn.execute(text("PRAGMA table_info(users)"))
                existing_cols = {row[1] for row in cols_res.fetchall()}
                if "persona" not in existing_cols:
                    await conn.execute(
                        text("ALTER TABLE users ADD COLUMN persona VARCHAR(50) DEFAULT 'nakama'")
                    )
                if "xp" not in existing_cols:
                    await conn.execute(
                        text("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
                    )
                # Ensure files table has channel_message_id
                f_cols = await conn.execute(text("PRAGMA table_info(files)"))
                f_existing = {row[1] for row in f_cols.fetchall()}
                if "channel_message_id" not in f_existing:
                    await conn.execute(
                        text("ALTER TABLE files ADD COLUMN channel_message_id INTEGER")
                    )
            else:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN IF NOT EXISTS persona VARCHAR(50) DEFAULT 'nakama'")
                )
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN IF NOT EXISTS xp INTEGER DEFAULT 0")
                )
                await conn.execute(
                    text("ALTER TABLE files ADD COLUMN IF NOT EXISTS channel_message_id BIGINT")
                )
        except Exception:
            pass


async def close_db() -> None:
    """Dispose the engine connection pool."""
    await engine.dispose()
