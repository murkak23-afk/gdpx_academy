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
        # TTLCache автоматически чистит старые записи
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
        """Основной метод middleware с полной защитой от None-handler."""

        if handler is None:
            return None

        if not isinstance(event, Update):
            return await handler(event, data)

        # ПРОПУСКАЕМ ГРУППОВЫЕ ЧАТЫ (для авто-фикса)
        if event.message and event.message.chat.type in ["group", "supergroup"]:
            return await handler(event, data)

        # ПРОПУСКАЕМ МЕДИА (для скоростной загрузки)
        if _is_bulk_upload_message(event):
            return await handler(event, data)

        # ctx: EventContext | None = data.get(EVENT_CONTEXT_KEY)
        # uid = ctx.user_id if ctx else None
        
        # Берем напрямую из апдейта
        user = event.message.from_user if event.message else (event.callback_query.from_user if event.callback_query else None)
        uid = user.id if user else None
        
        if uid is None:
            return await handler(event, data)

        # === BULK RATE LIMITING (max ~4 файла в секунду) ===
        if _is_bulk_upload_message(event):
            now = time.monotonic()
            uid = getattr(event.from_user, 'id', 0) if hasattr(event, 'from_user') else 0
            bulk_key = (uid, "bulk")

            async with self._lock:
                if bulk_key not in self._last_ts:
                    self._last_ts[bulk_key] = now - 0.25

                prev = self._last_ts[bulk_key]
                next_allowed = max(now, prev + 0.25)
                self._last_ts[bulk_key] = next_allowed

                delay = next_allowed - now
                if delay > 0:
                    await asyncio.sleep(delay)

            return await handler(event, data)

        # === ОБЫЧНЫЙ THROTTLING ===
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
                # logger.debug("throttle: user %s skip (interval %ss)", uid, interval)
                return None
            self._last_ts[key] = now

        return await handler(event, data)
