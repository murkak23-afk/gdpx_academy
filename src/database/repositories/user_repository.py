from sqlalchemy import select
from src.database.models.user import User
from src.database.repositories.base import BaseRepository
from typing import Optional

class UserRepository(BaseRepository[User]):
    def __init__(self, session):
        super().__init__(model=User, session=session)

    async def get_by_telegram_id(self, tg_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.telegram_id == tg_id))
        return result.scalars().first()

    async def get_all_admins(self) -> list[User]:
        from src.database.models.enums import UserRole
        stmt = select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active_users(self) -> list[User]:
        stmt = select(User).where(User.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_sellers(self) -> list[User]:
        from src.database.models.enums import UserRole
        stmt = (
            select(User)
            .where(
                User.is_active.is_(True),
                User.role.in_((UserRole.SELLER, UserRole.ADMIN)),
            )
            .order_by(User.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
