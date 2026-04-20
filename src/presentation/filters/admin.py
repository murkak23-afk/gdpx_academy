from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.moderation.admin_service import AdminService


class IsAdminFilter(BaseFilter):
    """Пропускает апдейт только для Модератора (роль 'admin')."""

    async def __call__(self, event: TelegramObject, session: AsyncSession) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False

        return await AdminService(session=session).is_admin_strictly(user.id)


class IsOwnerFilter(BaseFilter):
    """Пропускает апдейт только для Владельца (роль 'owner' или ID из .env)."""

    async def __call__(self, event: TelegramObject, session: AsyncSession) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False

        return await AdminService(session=session).is_owner_strictly(user.id)
