"""Ограничение частоты апдейтов на пользователя (анти-спам)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.middlewares.user_context import EVENT_CONTEXT_KEY, EventContext
from aiogram.types import TelegramObject, Update
from cachetools import TTLCache

logger = logging.getLogger(__name__)


def _is_bulk_upload_message(event: Update) -> bool:
    """Пропускает burst медиа-сообщений для загрузки товаров без throttling."""

    msg = event.message
    if msg is None:
        return False
    # Пачки товаров приходят как много отдельных сообщений с фото/документом,
    # иногда пересланных и/или в media group.
    return bool(msg.photo or msg.document or msg.media_group_id)


class UserThrottlingMiddleware(BaseMiddleware):
    """Не чаще одного «логического» апдейта от пользователя за interval_sec (по умолчанию 1 с)."""

    def __init__(self, interval_sec: float = 1.0) -> None:
        self._interval = max(interval_sec, 0.05)
        self._last_ts: TTLCache[tuple[int, str], float] = TTLCache(maxsize=10000, ttl=600)
        self._lock = asyncio.Lock()

    @staticmethod
    def _callback_key(event: Update) -> str | None:
        cb = event.callback_query
        if cb is None:
            return None
        # Для callback throttling применяем только к повторам одной и той же кнопки.
        return cb.data or "<empty>"

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

        if _is_bulk_upload_message(event):
            return await handler(event, data)

        callback_key = self._callback_key(event)
        if callback_key is not None:
            key = (uid, f"cb:{callback_key}")
            interval = min(self._interval, 0.35)
        else:
            key = (uid, "generic")
            interval = self._interval

        now = time.monotonic()
        async with self._lock:
            prev = self._last_ts.get(key, 0.0)
            if now - prev < interval:
                logger.warning(
                    "throttle: пропуск update_id=%s user_id=%s (min interval %ss)",
                    event.update_id,
                    uid,
                    interval,
                )
                return None
            self._last_ts[key] = now

        return await handler(event, data)
