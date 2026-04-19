from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.core.config import Settings
from src.domain.moderation.admin_service import AdminService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class MaintenanceMiddleware(BaseMiddleware):
    """
    Middleware для режима технического обслуживания.
    Блокирует селлеров, если MAINTENANCE_MODE=True.
    Пропускает OWNER_TELEGRAM_IDS и пользователей с ролью 'admin'.
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

        # Теперь мы работаем только с Message или CallbackQuery (согласно регистрации в dispatcher.py)
        user_id = getattr(event, "from_user", None).id if hasattr(event, "from_user") else None
        
        if not user_id:
            logger.warning(f"MaintenanceMiddleware: Could not extract user_id from {type(event)}")
            return await handler(event, data)

        # 1. Проверка Владельцев (Hardware-level)
        if user_id in self.settings.owner_telegram_ids:
            return await handler(event, data)

        # 2. Проверка Ролей (Database-level)
        session: AsyncSession = data.get("session")
        if session:
            try:
                admin_svc = AdminService(session=session)
                if await admin_svc.is_admin_strictly(user_id) or await admin_svc.is_owner_strictly(user_id):
                    return await handler(event, data)
            except Exception as e:
                logger.error(f"MaintenanceMiddleware check error for {user_id}: {e}")

        # Блокировка
        logger.info(f"🚧 BLOCKED during maintenance: {user_id} (@{getattr(event.from_user, 'username', 'N/A')}) attempted {type(event)}")

        if isinstance(event, Message):
            is_start = event.text and event.text.startswith("/start")
            if is_start:
                msg = (
                    "⚙️ <b>GDPX // MAINTENANCE MODE</b>\n"
                    "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                    "В данный момент в терминале проводятся технические работы.\n\n"
                    "▫ <b>Статус:</b> <code>RESTRICTED ACCESS</code>\n"
                    "▫ <b>Допуск:</b> Только для персонала Синдиката\n\n"
                    "<i>Пожалуйста, попробуйте войти позже. Мы сообщим о возобновлении работы в официальном канале.</i>"
                )
                await event.answer(msg, parse_mode="HTML")
            else:
                maintenance_text = (
                    "🚧 <b>ТЕХНИЧЕСКИЙ ПЕРЕРЫВ</b>\n\n"
                    "Терминал временно переведен в режим обслуживания.\n"
                    "Доступ для агентов ограничен. Мы скоро вернемся."
                )
                await event.answer(maintenance_text, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer("🚧 Режим обслуживания", show_alert=True)
        
        return None
