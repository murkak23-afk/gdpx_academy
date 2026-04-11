import asyncio
import sys
import os

# Добавляем корень проекта в PYTHONPATH
sys.path.append(os.getcwd())

from sqlalchemy import text
from src.database.session import SessionFactory
from src.core.config import get_settings

async def update_enum():
    settings = get_settings()
    print(f"Connecting to: {settings.postgres_host}:{settings.postgres_port}...")
    
    async with SessionFactory() as session:
        try:
            # PostgreSQL не позволяет выполнять ALTER TYPE внутри транзакции в некоторых случаях,
            # но добавление значения обычно разрешено.
            # Используем session.execute с текстовым запросом.
            
            print("Adding 'in_work' to submission_status_enum...")
            # commit() обязателен, но ALTER TYPE ADD VALUE в Postgres 12+ 
            # можно делать только вне транзакционного блока в некоторых версиях,
            # либо просто выполнить и закоммитить.
            
            await session.execute(text("ALTER TYPE submission_status_enum ADD VALUE 'in_work'"))
            await session.commit()
            print("Successfully added 'in_work' to enum!")
        except Exception as e:
            if "already exists" in str(e):
                print("Value 'in_work' already exists in enum.")
            else:
                print(f"Error: {e}")
                await session.rollback()

if __name__ == "__main__":
    asyncio.run(update_enum())
