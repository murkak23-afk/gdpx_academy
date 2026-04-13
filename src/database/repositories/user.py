from __future__ import annotations

from sqlalchemy import select
from src.database.models.user import User
from src.database.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session):
        super().__init__(User, session)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        query = select(self.model).where(self.model.telegram_id == telegram_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
