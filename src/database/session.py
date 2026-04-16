from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
import orjson

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=40,          # Увеличено для высоких нагрузок
    max_overflow=20,       # Максимальный доп. лимит
    pool_timeout=30,
    pool_recycle=1800,     # Пересоздавать соединение каждые 30 мин
    json_serializer=lambda v: orjson.dumps(v).decode(),
    json_deserializer=orjson.loads,
    connect_args={
        "statement_cache_size": 100,
        "prepared_statement_cache_size": 100,
        "command_timeout": 60,
    }
)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False, # Ускоряет работу, если не нужны частые flush
)


async def get_db_session() -> AsyncSession:
    """DI-генератор сессии для хендлеров и сервисов."""

    async with SessionFactory() as session:
        yield session
