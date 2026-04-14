import asyncio
import sys
import os

# Добавляем путь к проекту
sys.path.append(os.getcwd())

from sqlalchemy import select
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.web_control import WebAccount

# Прямой импорт, минуя __init__.py
from src.services.auth_service import AuthService

async def create_owner_account(login, password, tg_id):
    async with SessionFactory() as session:
        # 1. Ищем пользователя в боте по TG ID
        stmt = select(User).where(User.telegram_id == int(tg_id))
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ Ошибка: Пользователь с TG ID {tg_id} не найден в базе бота. Сначала напишите боту /start")
            return

        # 2. Создаем веб-аккаунт
        hashed_pwd = AuthService.hash_password(password)
        
        # Проверяем, нет ли уже такого аккаунта
        stmt_web = select(WebAccount).where(WebAccount.user_id == user.id)
        result_web = await session.execute(stmt_web)
        existing = result_web.scalar_one_or_none()

        if existing:
            existing.login = login
            existing.password_hash = hashed_pwd
            print(f"🔄 Веб-аккаунт для ID {tg_id} обновлен (Логин: {login}).")
        else:
            new_acc = WebAccount(
                user_id=user.id,
                login=login,
                password_hash=hashed_pwd
            )
            session.add(new_acc)
            print(f"✅ Веб-аккаунт '{login}' успешно создан для @{user.username}")

        await session.commit()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Использование: python tools/create_web_user.py [ЛОГИН] [ПАРОЛЬ] [ВАШ_TG_ID]")
    else:
        asyncio.run(create_owner_account(sys.argv[1], sys.argv[2], sys.argv[3]))
