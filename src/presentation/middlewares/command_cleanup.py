from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)


class CommandCleanupMiddleware(BaseMiddleware):
    """
    Middleware для удаления входящих команд пользователя.
    Позволяет поддерживать интерфейс SMI в чистоте.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Если это сообщение и оно начинается с "/" (команда)
        if isinstance(event, Message) and event.text and event.text.startswith("/"):
            try:
                # Удаляем сообщение пользователя ДО обработки, чтобы в SMI оно исчезло сразу
                await event.delete()
            except Exception as e:
                logger.debug(f"Could not delete command message: {e}")

        # Выполняем хендлер (обработку команды)
        return await handler(event, data)
