
import asyncio
import logging
from sqlalchemy import text
from src.database.session import SessionFactory

async def fix_roles():
    async with SessionFactory() as session:
        # Обновляем старую роль 'simbuy' на 'seller' (так как simbuy больше нет в коде)
        result = await session.execute(
            text("UPDATE users SET role = 'seller' WHERE role = 'simbuy'")
        )
        await session.commit()
        print(f"✅ Исправлено строк: {result.rowcount}")

if __name__ == "__main__":
    asyncio.run(fix_roles())
