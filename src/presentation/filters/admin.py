from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.moderation.admin_service import AdminService


class IsAdminFilter(BaseFilter):
    """Пропускает апдейт только для Модератора (роль 'admin')."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        if message.from_user is None:
            return False

        return await AdminService(session=session).is_admin_strictly(message.from_user.id)


class IsOwnerFilter(BaseFilter):
    """Пропускает апдейт только для Владельца (роль 'owner' или ID из .env)."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        if message.from_user is None:
            return False

        return await AdminService(session=session).is_owner_strictly(message.from_user.id)
