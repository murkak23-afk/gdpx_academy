from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import AdminService


class IsChiefAdminFilter(BaseFilter):
    """Пропускает апдейт только для админа (чтобы seller-FSM не перехватывал кнопки админ-меню)."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        if message.from_user is None:
            return False
        return await AdminService(session=session).is_admin(message.from_user.id)
