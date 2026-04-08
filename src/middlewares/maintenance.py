from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, Update
from src.core.config import Settings

logger = logging.getLogger(__name__)

class MaintenanceMiddleware(BaseMiddleware):
    """
    Middleware для режима технического обслуживания.
    Блокирует все апдейты, если MAINTENANCE_MODE=True, 
    за исключением пользователей из OWNER_TELEGRAM_IDS.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not self.settings.maintenance_mode:
            return await handler(event, data)

        # Извлекаем user_id из разных типов апдейтов
        user_id = None
        if isinstance(event, Update):
            if event.message:
                user_id = event.message.from_user.id
            elif event.callback_query:
                user_id = event.callback_query.from_user.id
        elif isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id

        # Если пользователь — владелец, пропускаем его
        if user_id in self.settings.owner_telegram_ids:
            return await handler(event, data)

        # Если это сообщение или колбэк — уведомляем пользователя
        maintenance_text = (
            "🚧 <b>Технические работы</b>\n\n"
            "В данный момент бот находится на обслуживании. "
            "Мы скоро вернемся! Благодарим за терпение."
        )

        if isinstance(event, Message):
            await event.answer(maintenance_text, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer("Бот на обслуживании 🚧", show_alert=True)
        
        return None
