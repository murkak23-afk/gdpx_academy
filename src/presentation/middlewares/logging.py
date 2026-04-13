"""Логирование входящих апдейтов с update_id и user_id для трассировки."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.middlewares.user_context import EVENT_CONTEXT_KEY, EventContext
from aiogram.types import TelegramObject, Update

logger = logging.getLogger(__name__)


class UpdateLoggingMiddleware(BaseMiddleware):
    """Пишет в лог каждый апдейт (после UserContext): update_id, user_id, тип события."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            ctx: EventContext | None = data.get(EVENT_CONTEXT_KEY)
            user_id = ctx.user_id if ctx else None
            try:
                ev_type = event.event_type
            except Exception:
                ev_type = "unknown"
            # INFO log will be sampled by logger config
            logger.info(
                "UP [%s] user=%s type=%s",
                event.update_id,
                user_id,
                ev_type,
            )
        return await handler(event, data)
