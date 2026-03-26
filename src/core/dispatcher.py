from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from src.database.session import SessionFactory
from src.handlers import setup_routers
from src.middlewares import DbSessionMiddleware

logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и подключает middleware/роутеры."""

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.middleware(DbSessionMiddleware(session_factory=SessionFactory))
    dispatcher.include_router(setup_routers())

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> None:
        """Логирует необработанные исключения (часто это сбой БД или Telegram API)."""

        logger.exception("Ошибка при обработке апдейта: %s", event.exception)

    return dispatcher
