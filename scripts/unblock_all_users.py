
import asyncio
from sqlalchemy import update
from src.database.session import SessionFactory
from src.database.models.user import User

async def unblock_all():
    async with SessionFactory() as session:
        # Полный сброс всех ограничений для всех пользователей
        stmt = (
            update(User)
            .values(
                is_restricted=False,
                duplicate_timeout_until=None,
                captcha_attempts=0
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        print(f"✅ Глобальный сброс ограничений выполнен для {result.rowcount} пользователей.")

if __name__ == "__main__":
    asyncio.run(unblock_all())
