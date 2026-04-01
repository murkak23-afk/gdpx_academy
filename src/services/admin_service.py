from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.category import Category
from src.database.models.enums import UserRole
from src.database.models.user import User


class AdminService:
    """Сервис административных операций."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _role_value(role: object | None) -> str:
        return str(getattr(role, "value", role or "")).strip().lower()

    @classmethod
    def _is_admin_role(cls, role: object | None) -> bool:
        # Временная совместимость: в части БД еще может жить legacy-роль chief_admin.
        return cls._role_value(role) in {"admin", "chief_admin"}

    async def is_admin(self, telegram_id: int) -> bool:
        """Проверяет, что пользователь имеет админскую роль."""

        stmt = select(User.role).where(User.telegram_id == telegram_id)
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._is_admin_role(role)

    async def can_use_sim_groups(self, telegram_id: int) -> bool:
        """Доступ к /sim и связанным групповым операциям очереди."""

        stmt = select(User.role).where(User.telegram_id == telegram_id)
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        role_value = self._role_value(role)
        return role_value in {"admin", "chief_admin", UserRole.SIM_ROOT.value}

    async def can_manage_payouts(self, telegram_id: int) -> bool:
        """Проверяет доступ к финансовой консоли (любой админ)."""

        return await self.is_admin(telegram_id)

    async def can_access_payout_finance(self, telegram_id: int) -> bool:
        """Доступ к разделу «Статистика», /withdraw и связанным финансовым экранам."""

        return await self.is_admin(telegram_id)

    async def create_category(
        self,
        title: str,
        payout_rate: Decimal,
        description: str | None,
        photo_file_id: str | None = None,
        total_upload_limit: int | None = None,
    ) -> Category:
        """Создает новую активную категорию (оператора)."""

        slug = await self._make_unique_slug(self._slugify(title))
        category = Category(
            title=title.strip(),
            slug=slug,
            payout_rate=payout_rate,
            description=description,
            photo_file_id=photo_file_id,
            total_upload_limit=total_upload_limit,
            is_active=True,
        )
        self._session.add(category)
        await self._session.commit()
        await self._session.refresh(category)
        return category

    @staticmethod
    def _slugify(value: str) -> str:
        """Упрощенный slug для категории."""

        slug = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", value.lower()).strip("-")
        return slug or "category"

    async def _make_unique_slug(self, base_slug: str) -> str:
        """Создает уникальный slug, добавляя числовой суффикс при конфликте."""

        slug = base_slug
        counter = 1
        while True:
            stmt = select(Category.id).where(Category.slug == slug)
            exists = (await self._session.execute(stmt)).scalar_one_or_none()
            if exists is None:
                return slug
            counter += 1
            slug = f"{base_slug}-{counter - 1}"
