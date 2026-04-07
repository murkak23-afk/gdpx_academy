from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import UserLanguage, UserRole
from src.database.models.user import User


class UserService:
    """Сервис регистрации и чтения профиля пользователя."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Возвращает пользователя по telegram_id."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        """Возвращает пользователя по внутреннему ID."""
        return await self._session.get(User, user_id)

    async def get_all_admins(self) -> list[User]:
        """Возвращает список всех пользователей с ролью admin."""
        stmt = select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active_users(self) -> list[User]:
        """Возвращает всех активных пользователей для рассылки."""
        stmt = select(User).where(User.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_sellers(self) -> list[User]:
        """Активные продавцы и админы (у кого может быть выгрузка) для «Запросов»."""
        stmt = (
            select(User)
            .where(
                User.is_active.is_(True),
                User.role.in_((UserRole.SELLER, UserRole.ADMIN)),
            )
            .order_by(User.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def register_seller(
        self,
        tg_user: TgUser,
        language: UserLanguage,
    ) -> User:
        """Регистрирует нового селлера или обновляет существующего."""

        existing = await self.get_by_telegram_id(telegram_id=tg_user.id)
        full_name = (f"{tg_user.first_name} {tg_user.last_name or ''}").strip()

        if existing is not None:
            existing.username = tg_user.username
            existing.full_name = full_name
            existing.language = language
            if existing.role is None:
                existing.role = UserRole.SELLER
            await self._session.refresh(existing)
            return existing

        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=full_name or "Unknown",
            language=language,
            role=UserRole.SELLER,
            is_active=True,
        )
        self._session.add(user)
        await self._session.refresh(user)
        return user

    async def set_restricted(self, user_id: int, value: bool) -> User | None:
        """Включает/выключает ограничение пользователя."""

        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.is_restricted = value
        if not value:
            user.captcha_answer = None
            user.captcha_attempts = 0
        await self._session.refresh(user)
        return user

    async def create_captcha(self, user_id: int) -> str | None:
        """Создает простую captcha-строку для снятия ограничения."""

        user = await self._session.get(User, user_id)
        if user is None:
            return None
        answer = str(random.randint(1000, 9999))
        user.captcha_answer = answer
        user.captcha_attempts = 0
        return answer

    async def verify_captcha(self, user_id: int, answer: str) -> bool:
        """Проверяет ответ captcha и снимает ограничение при успехе."""

        user = await self._session.get(User, user_id)
        if user is None:
            return False
        if not user.captcha_answer:
            return False
        if answer.strip() == user.captcha_answer:
            user.is_restricted = False
            user.captcha_answer = None
            user.captcha_attempts = 0
            return True
        user.captcha_attempts += 1
        return False

    async def set_duplicate_timeout(self, user_id: int, minutes: int = 60) -> User | None:
        """Устанавливает временный таймаут за повторы дублей."""

        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.duplicate_timeout_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        user.is_restricted = True
        await self._session.refresh(user)
        return user