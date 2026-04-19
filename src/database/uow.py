from __future__ import annotations

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.repositories import UserRepository, SubmissionRepository
from src.database.repositories.category import CategoryRepository

logger = logging.getLogger(__name__)

class UnitOfWork:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.submissions = SubmissionRepository(session)
        self.categories = CategoryRepository(session)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                await self.rollback()
            else:
                await self.commit()
        except Exception as e:
            logger.error(f"Error in UoW commit/rollback: {e}", exc_info=True)
            await self.rollback()
            raise
        finally:
            await self.session.close()

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
