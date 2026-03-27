"""Ограничение частоты апдейтов на пользователя (анти-спам)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.middlewares.user_context import EVENT_CONTEXT_KEY, EventContext
from aiogram.types import TelegramObject, Update

logger = logging.getLogger(__name__)


class UserThrottlingMiddleware(BaseMiddleware):
    """Не чаще одного «логического» апдейта от пользователя за interval_sec (по умолчанию 1 с)."""

    def __init__(self, interval_sec: float = 1.0) -> None:
        self._interval = max(interval_sec, 0.05)
        self._last_ts: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        ctx: EventContext | None = data.get(EVENT_CONTEXT_KEY)
        uid = ctx.user_id if ctx else None
        if uid is None:
            return await handler(event, data)

        now = time.monotonic()
        async with self._lock:
            prev = self._last_ts.get(uid, 0.0)
            if now - prev < self._interval:
                logger.warning(
                    "throttle: пропуск update_id=%s user_id=%s (min interval %ss)",
                    event.update_id,
                    uid,
                    self._interval,
                )
                return None
            self._last_ts[uid] = now

        return await handler(event, data)
