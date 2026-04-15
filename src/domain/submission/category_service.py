from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.category import Category


class CategoryService:
    """Сервис управления категориями eSIM."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_category(
        self,
        title: str,
        operator: str,
        sim_type: str,
        payout_rate: Decimal,
        is_active: bool = True,
    ) -> Category:
        """Создает новую категорию (кластер) в БД."""
        import re
        import uuid

        # Генерируем безопасный уникальный slug
        base_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}" if base_slug else uuid.uuid4().hex[:12]

        category = Category(
            title=title.strip(),
            slug=unique_slug,
            operator=operator.strip(),
            sim_type=sim_type.strip(),
            payout_rate=payout_rate,
            is_active=is_active,
        )

        self._session.add(category)
        await self._session.flush()
        await self._session.refresh(category)
        return category

    async def get_active_categories(self) -> list[Category]:
        """Возвращает все активные категории."""
        stmt = select(Category).where(Category.is_active == True).order_by(Category.is_priority.desc(), Category.title.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_categories(self) -> list[Category]:
        """Возвращает все категории."""
        stmt = select(Category).order_by(Category.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, category_id: int) -> Category | None:
        """Ищет категорию по ID."""
        return await self._session.get(Category, category_id)

    async def set_active(self, category_id: int, is_active: bool) -> Category | None:
        """Включает/выключает категорию."""
        category = await self.get_by_id(category_id)
        if category:
            category.is_active = is_active
            await self._session.flush()
        return category

    async def update_payout_rate(self, category_id: int, payout_rate: Decimal) -> Category | None:
        """Обновляет базовую цену."""
        category = await self.get_by_id(category_id)
        if category:
            category.payout_rate = payout_rate
            await self._session.flush()
        return category

    async def set_priority(self, category_id: int, is_priority: bool) -> Category | None:
        """Включает/выключает приоритет."""
        category = await self.get_by_id(category_id)
        if category:
            category.is_priority = is_priority
            await self._session.flush()
        return category
