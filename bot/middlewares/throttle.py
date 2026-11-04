"""Simple in-memory rate-limiting middleware."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import settings


class ThrottleMiddleware(BaseMiddleware):
    """Rate limit users to prevent spam / abuse.

    Tracks message timestamps per user in memory. If a user exceeds
    `settings.rate_limit` messages in 60 seconds, replies with a warning.
    """

    def __init__(self) -> None:
        self._timestamps: dict[int, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        uid = user.id
        now = time.monotonic()
        window = 60.0  # 1-minute window

        # Purge old timestamps
        self._timestamps[uid] = [
            ts for ts in self._timestamps[uid] if now - ts < window
        ]

        if len(self._timestamps[uid]) >= settings.rate_limit:
            if isinstance(event, Message):
                await event.answer(
                    "⏳ You're sending messages too fast. Please wait a moment."
                )
            return None

        self._timestamps[uid].append(now)
        return await handler(event, data)
