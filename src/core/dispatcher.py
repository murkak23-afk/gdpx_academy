from __future__ import annotations

import logging

from aiogram import Dispatcher

from src.core.config import get_settings

from src.core.error_handlers import register_error_handlers
from src.core.fsm_storage import build_fsm_storage
from src.database.session import SessionFactory
from src.presentation.routers import setup_routers
from src.presentation.middlewares import (
    DbSessionMiddleware,
    UpdateLoggingMiddleware,
    UserThrottlingMiddleware,
    LoadingMiddleware,
)
from src.presentation.middlewares.command_cleanup import CommandCleanupMiddleware
from src.presentation.middlewares.block_check import BlockCheckMiddleware
from src.presentation.middlewares.maintenance import MaintenanceMiddleware
from src.presentation.middlewares.fsm_timeout import FSMTimeoutMiddleware
from src.core.utils.message_manager import MessageManager
from src.core.logger import logger


def create_dispatcher(ws_manager=None) -> Dispatcher:
    """Создаёт диспетчер и подключает middleware/роутеры/обработчик ошибок."""

    dispatcher = Dispatcher(storage=build_fsm_storage())
    dispatcher["ws_manager"] = ws_manager
    
    # Инициализация SMI MessageManager
    from src.core.bot import create_bot
    bot = create_bot()
    mm = MessageManager(bot)
    
    @dispatcher.update.outer_middleware()
    async def smi_middleware(handler, event, data):
        data["ui"] = mm
        return await handler(event, data)
    settings = get_settings()

    @dispatcher.update.outer_middleware()
    async def global_debug_middleware(handler, event, data):
        user = data.get("event_from_user")
        msg = data.get("event_chat") # На самом деле лучше брать из самого event если это Update
        from aiogram.types import Update
        if isinstance(event, Update) and event.message:
            logger.info(f"!!! [GLOBAL_TRACE] !!! Message from {user.id} (@{user.username}): '{event.message.text}' in chat {event.message.chat.id}")
        elif user:
            logger.info(f"!!! [GLOBAL_TRACE] !!! Update from {user.id} (@{user.username})")
        return await handler(event, data)

    # ПЕРЕВОДИМ В OUTER MIDDLEWARE (выполняются ВСЕГДА до роутеров)
    dispatcher.update.outer_middleware(CommandCleanupMiddleware()) # ЧИСТКА КОМАНД СРАЗУ
    dispatcher.update.outer_middleware(FSMTimeoutMiddleware(timeout_seconds=86400)) # СБРОС СТЕЙТА ПО ТАЙМАУТУ
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory=SessionFactory))
    dispatcher.update.outer_middleware(BlockCheckMiddleware())
    dispatcher.update.outer_middleware(LoadingMiddleware())

    # Порядок: сначала логирование, затем техработы.
    dispatcher.update.middleware(UpdateLoggingMiddleware())
    dispatcher.message.middleware(MaintenanceMiddleware(settings=settings))
    dispatcher.callback_query.middleware(MaintenanceMiddleware(settings=settings))
    dispatcher.update.middleware(UserThrottlingMiddleware(interval_sec=1.0))
    dispatcher.message.outer_middleware(CommandCleanupMiddleware())

    dispatcher.include_router(setup_routers())
    register_error_handlers(dispatcher)

    return dispatcher
