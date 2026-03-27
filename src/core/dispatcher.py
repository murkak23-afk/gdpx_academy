from __future__ import annotations

from aiogram import Dispatcher

from src.core.error_handlers import register_error_handlers
from src.core.fsm_storage import build_fsm_storage
from src.database.session import SessionFactory
from src.handlers import setup_routers
from src.middlewares import (
    DbSessionMiddleware,
    UpdateLoggingMiddleware,
    UserThrottlingMiddleware,
)


def create_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и подключает middleware/роутеры/обработчик ошибок."""

    dispatcher = Dispatcher(storage=build_fsm_storage())

    # Порядок: сначала throttling, затем логирование, затем сессия БД (первый зарегистрированный — внешний).
    dispatcher.update.middleware(UserThrottlingMiddleware(interval_sec=1.0))
    dispatcher.update.middleware(UpdateLoggingMiddleware())
    dispatcher.update.middleware(DbSessionMiddleware(session_factory=SessionFactory))

    dispatcher.include_router(setup_routers())
    register_error_handlers(dispatcher)

    return dispatcher
