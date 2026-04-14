import asyncio
import sys
import os

# Добавляем корень проекта в пути поиска модулей
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from passlib.hash import argon2
from src.database.session import SessionFactory
from src.database.models.web_control import WebAccount
from sqlalchemy import select

async def reset_password(login: str, new_password: str):
    async with SessionFactory() as session:
        stmt = select(WebAccount).where(WebAccount.login == login)
        acc = (await session.execute(stmt)).scalar_one_or_none()
        
        if acc:
            acc.password_hash = argon2.hash(new_password)
            await session.commit()
            print(f"✅ Пароль для '{login}' успешно сброшен на 'admin123'!")
        else:
            print(f"❌ Аккаунт с логином '{login}' не найден!")

if __name__ == '__main__':
    # Сбрасываем на 'admin123' для входа
    asyncio.run(reset_password("dyachx", "admin123"))
