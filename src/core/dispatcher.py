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
from src.middlewares.maintenance import MaintenanceMiddleware
from src.middlewares.block_check import BlockCheckMiddleware
from src.core.config import get_settings


def create_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и подключает middleware/роутеры/обработчик ошибок."""

    dispatcher = Dispatcher(storage=build_fsm_storage())
    settings = get_settings()

    # Порядок: сначала throttling, затем логирование.
    dispatcher.update.middleware(UserThrottlingMiddleware(interval_sec=1.0))
    
    @dispatcher.update.outer_middleware()
    async def global_debug_middleware(handler, event, data):
        user = data.get("event_from_user")
        if user:
            from src.core.logger import logger
            logger.info(f"!!! [GLOBAL_TRACE] !!! Update from {user.id} (@{user.username})")
        return await handler(event, data)

    dispatcher.update.middleware(UpdateLoggingMiddleware())
    
    # ПЕРЕВОДИМ В OUTER MIDDLEWARE (выполняются ВСЕГДА до роутеров)
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory=SessionFactory))
    dispatcher.update.outer_middleware(MaintenanceMiddleware(settings=settings))
    dispatcher.update.outer_middleware(BlockCheckMiddleware())

    dispatcher.include_router(setup_routers())
    register_error_handlers(dispatcher)

    return dispatcher
