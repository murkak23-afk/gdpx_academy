from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import AdminService


class IsAdminFilter(BaseFilter):
    """Пропускает апдейт только для админа (проверка по конфигу + БД)."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        if message.from_user is None:
            return False

        uid = message.from_user.id

        # 1. Быстрая проверка по статическому списку (конфиг)
        from src.core.config import get_settings
        settings = get_settings()
        if uid in settings.admin_telegram_ids:
            return True

        # 2. Проверка роли в базе данных
        return await AdminService(session=session).is_admin(uid)
