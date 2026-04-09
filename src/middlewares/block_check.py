from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models.user import User

logger = logging.getLogger(__name__)

class BlockCheckMiddleware(BaseMiddleware):
    """
    Middleware для проверки блокировки пользователя.
    Если User.is_restricted=True, блокирует доступ к боту.
    Должен стоять ПОСЛЕ DbSessionMiddleware.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Извлекаем пользователя из любого типа апдейта
        from aiogram.types import User as TGUser
        user: TGUser = data.get("event_from_user")
        
        if not user:
            return await handler(event, data)

        session: AsyncSession = data.get("session")
        if not session:
            # Если по какой-то причине сессии нет (хотя DbSessionMiddleware стоит выше)
            return await handler(event, data)

        # Проверяем статус в БД
        stmt = select(User.is_restricted).where(User.telegram_id == user.id)
        result = await session.execute(stmt)
        is_restricted = result.scalar()

        if is_restricted:
            logger.warning(f"Blocked user {user.id} (@{user.username}) tried to access the bot.")
            
            block_text = (
                "🚫 <b>ДОСТУП ЗАБЛОКИРОВАН</b>\n\n"
                "Ваш аккаунт был ограничен администрацией.\n"
                "Если вы считаете, что это ошибка, обратитесь в поддержку."
            )
            
            # Пытаемся ответить пользователю в зависимости от типа события
            try:
                if isinstance(event, Message):
                    await event.answer(block_text, parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Ваш аккаунт заблокирован 🚫", show_alert=True)
            except Exception:
                pass # Пользователь мог заблокировать бота
                
            return None

        return await handler(event, data)
