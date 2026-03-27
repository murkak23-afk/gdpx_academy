from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.category import Category


class CategoryService:
    """Сервис чтения категорий для пользовательского меню."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_categories(self) -> list[Category]:
        """Возвращает все активные категории."""

        stmt = select(Category).where(Category.is_active.is_(True)).order_by(Category.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_categories(self) -> list[Category]:
        """Возвращает все категории (активные и неактивные)."""

        stmt = select(Category).order_by(Category.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_title(self, title: str) -> Category | None:
        """Ищет категорию по названию."""

        stmt = select(Category).where(Category.title == title, Category.is_active.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, category_id: int) -> Category | None:
        """Ищет категорию по ID."""

        return await self._session.get(Category, category_id)

    async def get_total_uploaded_count(self, category_id: int) -> int:
        """Считает общее количество загруженных товаров в категории."""

        from src.database.models.submission import Submission

        stmt = select(func.count(Submission.id)).where(Submission.category_id == category_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def set_total_limit(self, category_id: int, total_limit: int | None) -> Category | None:
        """Устанавливает общий лимит загрузок по категории."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.total_upload_limit = total_limit
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def set_active(self, category_id: int, is_active: bool) -> Category | None:
        """Включает/выключает категорию (soft-delete через is_active)."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.is_active = is_active
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def update_payout_rate(self, category_id: int, payout_rate: Decimal) -> Category | None:
        """Обновляет цену за единицу (USDT) в поле `payout_rate`)."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.payout_rate = payout_rate
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def update_description(self, category_id: int, description: str | None) -> Category | None:
        """Обновляет описание категории."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.description = description
        await self._session.commit()
        await self._session.refresh(category)
        return category
