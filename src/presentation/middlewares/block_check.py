from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import UserCache
from src.database.models.user import User

logger = logging.getLogger(__name__)

class BlockCheckMiddleware(BaseMiddleware):
    """
    Middleware для проверки блокировки пользователя.
    Использует Redis-кэш (TTL 45с) для снижения нагрузки на БД.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Извлекаем пользователя
        user_tg = data.get("event_from_user")
        if not user_tg:
            return await handler(event, data)

        # 1. Проверяем кэш
        cached_status = await UserCache.get_status(user_tg.id)
        if cached_status is not None:
            is_restricted = cached_status["is_restricted"]
            data["user_role"] = cached_status["role"]
        else:
            # 2. Кэша нет — идем в БД
            session: AsyncSession = data.get("session")
            if not session:
                return await handler(event, data)

            stmt = select(User.is_restricted, User.role).where(User.telegram_id == user_tg.id)
            result = await session.execute(stmt)
            row = result.fetchone()
            
            if not row:
                # Юзера нет в БД (первый запуск), пропускаем, чтобы он мог нажать /start
                return await handler(event, data)

            is_restricted, role = row
            # 3. Сохраняем в кэш на 45 секунд
            await UserCache.set_status(user_tg.id, is_restricted, role.value if hasattr(role, "value") else str(role))
            data["user_role"] = role

        if is_restricted:
            # Владельцев нельзя блокировать через этот механизм
            from src.core.config import get_settings
            if user_tg.id in get_settings().owner_telegram_ids:
                return await handler(event, data)

            block_text = (
                "🚫 <b>ДОСТУП ЗАБЛОКИРОВАН</b>\n\n"
                "Ваш аккаунт был ограничен администрацией."
            )
            try:
                if isinstance(event, Message):
                    await event.answer(block_text, parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Заблокировано 🚫", show_alert=True)
            except Exception:
                pass
            return None

        return await handler(event, data)
