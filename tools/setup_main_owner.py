import asyncio
import sys
import os

# Добавляем корень проекта в пути поиска модулей
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.models.enums import UserRole
from src.database.models.user import User
from src.database.models.web_control import WebAccount
from src.database.session import SessionFactory
from src.services.auth_service import AuthService
from sqlalchemy import select

async def setup_main_owner():
    tg_id = 8118820086
    login = "brug0s"
    password = "77712377"
    
    async with SessionFactory() as session:
        # 1. Ищем или создаем пользователя
        stmt = select(User).where(User.telegram_id == tg_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        
        if not user:
            print(f"Пользователь с TG ID {tg_id} не найден, создаю нового...")
            user = User(
                telegram_id=tg_id,
                full_name="Main Owner",
                role=UserRole.OWNER,
                is_active=True
            )
            session.add(user)
            await session.flush()
        else:
            print(f"Пользователь {user.full_name} найден, повышаю до OWNER...")
            user.role = UserRole.OWNER
            user.is_active = True

        # 2. Ищем или создаем веб-аккаунт
        stmt_web = select(WebAccount).where(WebAccount.user_id == user.id)
        web_acc = (await session.execute(stmt_web)).scalar_one_or_none()
        
        hashed_pw = AuthService.hash_password(password)
        
        if not web_acc:
            print(f"Создаю веб-аккаунт с логином '{login}'...")
            web_acc = WebAccount(
                user_id=user.id,
                login=login,
                password_hash=hashed_pw,
                is_active=True
            )
            session.add(web_acc)
        else:
            print(f"Обновляю веб-аккаунт '{login}'...")
            web_acc.login = login
            web_acc.password_hash = hashed_pw
            web_acc.is_active = True
            
        await session.commit()
        print(f"✅ Готово! Капитан, теперь ты Main OWNER.")
        print(f"Логин: {login}")
        print(f"Пароль: {password}")

if __name__ == '__main__':
    asyncio.run(setup_main_owner())
