import asyncio
import sys
import os

# Добавляем корень проекта в пути поиска модулей
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.models.enums import UserRole
from src.database.models.user import User
from src.database.models.web_control import WebAccount
from src.database.session import SessionFactory
from sqlalchemy import select

async def sync_web_owner(login: str, tg_id: int):
    async with SessionFactory() as session:
        # 1. Ищем пользователя по TG ID
        user_stmt = select(User).where(User.telegram_id == tg_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        
        if not user:
            print(f"❌ Пользователь с TG ID {tg_id} не найден!")
            return

        # 2. Ищем веб-аккаунт по логину
        web_stmt = select(WebAccount).where(WebAccount.login == login)
        web_acc = (await session.execute(web_stmt)).scalar_one_or_none()
        
        if not web_acc:
            print(f"❌ Веб-аккаунт с логином '{login}' не найден!")
            return

        # 3. Синхронизируем: роль OWNER и связь с правильным user_id
        user.role = UserRole.OWNER
        web_acc.user_id = user.id
        
        await session.commit()
        print(f"✅ Готово! Логин '{login}' теперь связан с пользователем {user.full_name} (ID: {user.id})")
        print(f"✅ Роль в базе подтверждена: {user.role.value}")

if __name__ == '__main__':
    login = "dyachx"
    tg_id = 8118820086
    asyncio.run(sync_web_owner(login, tg_id))
