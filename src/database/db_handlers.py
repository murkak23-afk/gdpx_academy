"""Готовые async-функции для частых операций с БД.

Используют SessionFactory напрямую — не требуют передавать сессию.
Удобны там, где нет DI-инъекции (фоновые задачи, скрипты, мониторинг).
Для работы внутри хендлеров aiogram предпочтительнее сервисы через
инжектированную сессию (session: AsyncSession из middleware).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import User as TgUser

from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserLanguage
from src.database.models.submission import Submission
from src.database.models.user import User
from src.database.session import SessionFactory
from src.services.category_service import CategoryService
from src.services.submission_service import SubmissionService
from src.services.user_service import UserService

if TYPE_CHECKING:
    from decimal import Decimal


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    """Возвращает пользователя по telegram_id или None."""
    async with SessionFactory() as session:
        return await UserService(session).get_by_telegram_id(telegram_id)


async def register_or_update_user(tg_user: TgUser, language: UserLanguage) -> User:
    """Регистрирует нового или обновляет существующего пользователя."""
    async with SessionFactory() as session:
        return await UserService(session).register_seller(tg_user, language)


async def get_all_active_users() -> list[User]:
    """Возвращает всех активных пользователей (для рассылок, мониторинга)."""
    async with SessionFactory() as session:
        return await UserService(session).get_all_active_users()


# ---------------------------------------------------------------------------
# Категории
# ---------------------------------------------------------------------------


async def get_active_categories() -> list[Category]:
    """Возвращает список активных категорий (операторов)."""
    async with SessionFactory() as session:
        return await CategoryService(session).get_active_categories()


# ---------------------------------------------------------------------------
# Заявки (submissions)
# ---------------------------------------------------------------------------


async def get_user_dashboard(user_id: int) -> dict[str, object]:
    """Возвращает статистику дашборда пользователя: pending/accepted/rejected/balance."""
    async with SessionFactory() as session:
        return await SubmissionService(session).get_user_dashboard_stats(user_id=user_id)


async def count_user_submissions_today(user_id: int) -> int:
    """Считает, сколько заявок пользователь подал сегодня (UTC)."""
    async with SessionFactory() as session:
        return await SubmissionService(session).get_daily_count(user_id=user_id)


async def create_submission(
    user_id: int,
    category_id: int,
    telegram_file_id: str,
    file_unique_id: str,
    image_sha256: str,
    description_text: str,
    attachment_type: str = "photo",
) -> Submission:
    """Создаёт новую заявку в статусе pending."""
    async with SessionFactory() as session:
        return await SubmissionService(session).create_submission(
            user_id=user_id,
            category_id=category_id,
            telegram_file_id=telegram_file_id,
            file_unique_id=file_unique_id,
            image_sha256=image_sha256,
            description_text=description_text,
            attachment_type=attachment_type,
        )


async def is_duplicate_accepted(image_sha256: str) -> bool:
    """Проверяет, был ли хэш изображения уже принят ранее."""
    async with SessionFactory() as session:
        return await SubmissionService(session).is_duplicate_accepted(image_sha256)
