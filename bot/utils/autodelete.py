"""Auto-delete timer utility for copyright protection and clean chats."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

logger = logging.getLogger(__name__)

# Strong references to prevent GC during long sleeps
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _run_deletion(
    bot: Bot,
    chat_id: int,
    message_ids: list[int],
    delay_seconds: int,
) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug("Failed auto-deletion in chat %s: %s", chat_id, e)


async def schedule_deletion(
    bot: Bot,
    chat_id: int,
    message_ids: list[int],
    delay_seconds: int,
) -> None:
    """Delete messages after delay_seconds in an async background task."""
    await _run_deletion(bot, chat_id, message_ids, delay_seconds)


def start_schedule_deletion(
    bot: Bot,
    chat_id: int,
    message_ids: list[int],
    delay_seconds: int,
) -> asyncio.Task:
    """Spawn and track a background deletion task with strong GC reference."""
    task = asyncio.create_task(
        _run_deletion(bot, chat_id, message_ids, delay_seconds)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task
