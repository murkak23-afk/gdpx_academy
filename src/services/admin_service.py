from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.category import Category
from src.database.models.enums import UserRole
from src.database.models.user import User


class AdminService:
    """Сервис административных операций с иерархией OWNER > ADMIN."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _role_value(role: object | None) -> str:
        return str(getattr(role, "value", role or "")).strip().lower()

    async def is_owner(self, telegram_id: int) -> bool:
        """Проверяет, является ли пользователь Владельцем (из .env)."""
        from src.core.config import get_settings
        return telegram_id in get_settings().admin_telegram_ids

    async def is_admin(self, telegram_id: int) -> bool:
        """Владелец или любой админ из БД."""
        if await self.is_owner(telegram_id):
            return True
        
        stmt = select(User.role).where(User.telegram_id == telegram_id)
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._role_value(role) in {"admin", "chief_admin"}

    async def can_manage_payouts(self, telegram_id: int) -> bool:
        """Выплаты доступны ТОЛЬКО Владельцу."""
        return await self.is_owner(telegram_id)

    async def can_use_sim_groups(self, telegram_id: int) -> bool:
        """Доступ к /sim доступен любому админу/саппорту."""
        return await self.is_admin(telegram_id)

    async def can_edit_categories(self, telegram_id: int) -> bool:
        """Редактирование категорий доступно ТОЛЬКО Владельцу."""
        return await self.is_owner(telegram_id)

    async def create_category(
        self,
        title: str,
        payout_rate: Decimal,
        operator: str,
        sim_type: str,
        is_active: bool = True
    ) -> Category:
        """Создает новую категорию."""
        category = Category(
            title=title.strip(),
            slug=re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
            payout_rate=payout_rate,
            operator=operator,
            sim_type=sim_type,
            is_active=is_active,
        )
        self._session.add(category)
        return category
