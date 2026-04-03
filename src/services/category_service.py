from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy import delete as sql_delete
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
        await self._session.refresh(category)
        return category

    async def set_active(self, category_id: int, is_active: bool) -> Category | None:
        """Включает/выключает категорию (soft-delete через is_active)."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.is_active = is_active
        await self._session.refresh(category)
        return category

    async def update_payout_rate(self, category_id: int, payout_rate: Decimal) -> Category | None:
        """Обновляет цену за единицу (USDT) в поле `payout_rate`)."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.payout_rate = payout_rate
        await self._session.refresh(category)
        return category

    async def update_description(self, category_id: int, description: str | None) -> Category | None:
        """Обновляет описание категории."""

        category = await self.get_by_id(category_id)
        if category is None:
            return None
        category.description = description
        await self._session.refresh(category)
        return category

    async def delete_category(self, category_id: int) -> Literal["deleted", "deactivated", "not_found"]:
        """Удаляет категорию, если нет связанных submissions; иначе мягко выключает категорию.

        Возвращает:
        - "deleted": категория физически удалена;
        - "deactivated": категория связана с submissions и только выключена (is_active=False);
        - "not_found": категория не найдена.
        """

        category = await self.get_by_id(category_id)
        if category is None:
            return "not_found"

        from src.database.models.submission import Submission

        linked_stmt = select(func.count(Submission.id)).where(Submission.category_id == category_id)
        linked_count = int((await self._session.execute(linked_stmt)).scalar_one())
        if linked_count > 0:
            category.is_active = False
            await self._session.refresh(category)
            return "deactivated"

        await self._session.delete(category)
        return "deleted"

    async def force_delete_category(self, category_id: int) -> Literal["deleted", "not_found"]:
        """Принудительно удаляет категорию вместе со всеми связанными submissions."""

        category = await self.get_by_id(category_id)
        if category is None:
            return "not_found"

        from src.database.models.submission import Submission

        await self._session.execute(
            sql_delete(Submission)
            .where(Submission.category_id == category_id)
            .execution_options(synchronize_session=False)
        )
        await self._session.delete(category)
        return "deleted"
