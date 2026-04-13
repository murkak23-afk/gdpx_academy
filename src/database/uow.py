from __future__ import annotations

from typing import Type
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.repositories import UserRepository, SubmissionRepository
# Пока оставим CategoryRepository из старого пути, если он ещё не перенесён:
from src.database.repositories.category import CategoryRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.submissions = SubmissionRepository(session)
        self.categories = CategoryRepository(session)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self.session.close()

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
