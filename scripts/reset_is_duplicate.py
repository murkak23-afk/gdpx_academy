# Скрипт для сброса статуса is_duplicate у всех заявок в базе данных
# Используйте только если уверены, что хотите убрать отметку дубликата со всех заявок!

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.database.models.submission import Submission

# Замените на ваш DSN подключения к БД
DATABASE_URL = "sqlite+aiosqlite:///./db.sqlite3"  # или ваша строка подключения

async def reset_is_duplicate():
    engine = create_async_engine(DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        await session.execute(
            Submission.__table__.update().values(is_duplicate=False)
        )
        await session.commit()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_is_duplicate())
