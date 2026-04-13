from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Глобальный контекст для сессии (позволяет получать её в любой точке кода без пробрасывания)
db_session_ctx: ContextVar[AsyncSession] = ContextVar("db_session")

class DbSessionMiddleware(BaseMiddleware):
    """Открывает SQLAlchemy-сессию на каждый апдейт."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self._session_factory() as session:
            token = db_session_ctx.set(session)
            data["session"] = session
            try:
                result = await handler(event, data)
                # Коммитим только если не было ошибок и сессия не закрыта
                if session.is_active:
                    await session.commit()
                return result
            except Exception:
                if session.is_active:
                    await session.rollback()
                raise
            finally:
                db_session_ctx.reset(token)
