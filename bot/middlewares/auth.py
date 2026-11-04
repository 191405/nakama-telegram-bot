"""Admin authentication middleware."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import settings


class AdminMiddleware(BaseMiddleware):
    """Block non-admin users from admin-only handlers.

    Attach this middleware only to the admin router.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id not in settings.admin_id_list:
            if isinstance(event, Message):
                await event.answer("⛔ You are not authorized to use this command.")
            return None
        return await handler(event, data)
