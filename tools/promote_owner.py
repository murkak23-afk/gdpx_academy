import asyncio
import sys
import os

# Добавляем корень проекта в пути поиска модулей
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.models.enums import UserRole
from src.database.models.user import User
from src.database.session import SessionFactory
from sqlalchemy import select

async def make_owner(tg_id: int):
    async with SessionFactory() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            print(f"❌ Пользователь с TG ID {tg_id} не найден в базе!")
            return

        user.role = UserRole.OWNER
        await session.commit()
        print(f"✅ Пользователь {user.full_name} (@{user.username or 'N/A'}) теперь официальный OWNER!")

if __name__ == '__main__':
    tg_id = 8118820086
    asyncio.run(make_owner(tg_id))
