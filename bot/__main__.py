"""Bot entry point — wire up routers, middlewares, and start polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.db.engine import close_db, init_db
from bot.handlers import admin, callbacks, channel, features, inline, search, user

from bot.middlewares.auth import AdminMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.throttle import ThrottleMiddleware

if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and start the bot."""
    logger.info("Starting File Bot...")

    # ── Bot & Dispatcher ──────────────────────────────────────────────────
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # ── Database ──────────────────────────────────────────────────────────
    await init_db()
    logger.info("Database initialized.")

    # ── Global Middlewares ────────────────────────────────────────────────
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.inline_query.middleware(DbSessionMiddleware())
    dp.channel_post.middleware(DbSessionMiddleware())
    dp.message.middleware(ThrottleMiddleware())

    # ── Admin Middleware (only on admin router) ───────────────────────────
    admin.router.message.middleware(AdminMiddleware())
    admin.router.callback_query.middleware(AdminMiddleware())

    # ── Register Routers ─────────────────────────────────────────────────
    dp.include_routers(
        channel.router,
        admin.router,
        features.router,
        user.router,
        search.router,
        callbacks.router,
        inline.router,
    )


    # ── Set Bot Commands ─────────────────────────────────────────────────
    try:
        from aiogram.types import BotCommand

        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 Main menu & community stats"),
            BotCommand(command="feed", description="📺 Channel stream feed"),
            BotCommand(command="search", description="🔍 Search anime & episodes"),
            BotCommand(command="airing", description="📅 Airing today in Japan"),
            BotCommand(command="watchlist", description="🔖 My personal anime watchlist"),
            BotCommand(command="trivia", description="🎯 Daily anime trivia & XP"),
            BotCommand(command="leaderboard", description="🏆 Community bounty rankings"),
            BotCommand(command="persona", description="🎭 Switch AI character persona"),
            BotCommand(command="newchat", description="✨ Reset conversation memory"),
            BotCommand(command="whatanime", description="📸 Identify anime from screenshot"),
            BotCommand(command="themes", description="🎵 Opening & ending songs"),
            BotCommand(command="ask", description="🤖 Ask AI concierge (voice/text)"),
            BotCommand(command="profile", description="👤 My Nakama passport"),
            BotCommand(command="request", description="📩 Request missing anime"),
            BotCommand(command="help", description="ℹ️ User guide"),
        ])

    except Exception as e:
        logger.warning("Could not set bot commands (network issue): %s", e)

    # ── Start Polling with Auto-Reconnect ─────────────────────────────────
    logger.info("Bot is live! Polling for updates...")
    try:
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
                break
            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                logger.error("Network/polling error (%s). Reconnecting in 5 seconds...", e)
                await asyncio.sleep(5)
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Bot shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
