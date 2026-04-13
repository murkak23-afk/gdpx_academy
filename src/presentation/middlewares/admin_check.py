"""Middleware защиты admin-роутера: только пользователи из конфига или с ролью admin в БД."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger

_BLOCK_MSG = "[ ДОСТУП ЗАПРЕЩЕН // СИГНАТУРА НЕ РАСПОЗНАНА ]"


async def _deny(event: TelegramObject, text: str) -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=True)
        except Exception:
            pass
    elif isinstance(event, Message):
        # Молча удаляем сообщение — не раскрываем факт существования панели.
        try:
            await event.delete()
        except Exception:
            pass


class AdminAccessMiddleware(BaseMiddleware):
    """Применяется на конкретный роутер (admin_router), не на dispatcher.

    Алгоритм проверки:
      1. Если config.admin_telegram_ids непустой — проверяем только его (быстро, без БД).
      2. Если список пустой — fallback на DB-роль через AdminService (сессия уже в data).

    Регистрация (в setup_routers()):
        mw = AdminAccessMiddleware()
        admin_router.message.middleware(mw)
        admin_router.callback_query.middleware(mw)
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return None

        uid: int = user.id
        logger.debug("AdminAccessMiddleware: проверка доступа для user_id=%s", uid)

        # ── Быстрая проверка: статичный список из конфига ─────────────────
        from src.core.config import get_settings
        settings = get_settings()
        config_ids = settings.admin_telegram_ids
        
        logger.debug("AdminAccessMiddleware: ADMIN_TELEGRAM_IDS из конфига: %s", config_ids)

        if config_ids:
            if uid in config_ids:
                logger.debug("AdminAccessMiddleware: доступ РАЗРЕШЕН (по конфигу) для user_id=%s", uid)
                return await handler(event, data)
            
            logger.warning("AdminAccessMiddleware: отказ user_id=%s (не в ADMIN_TELEGRAM_IDS)", uid)
            await _deny(event, _BLOCK_MSG)
            return None

        # ── Fallback: проверка роли через БД (если список не настроен) ─────
        session = data.get("session")
        if session is None:
            # DbSessionMiddleware не выполнился — блокируем на всякий случай.
            logger.error("AdminAccessMiddleware: session отсутствует в data, блокируем user_id=%s", uid)
            await _deny(event, _BLOCK_MSG)
            return None

        from src.domain.moderation.admin_service import AdminService  # lazy — избегаем кругового импорта

        if await AdminService(session=session).is_admin(uid):
            return await handler(event, data)

        logger.warning("AdminAccessMiddleware: отказ user_id=%s (нет роли admin в БД)", uid)
        await _deny(event, _BLOCK_MSG)
        return None
