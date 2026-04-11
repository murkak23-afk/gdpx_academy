from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

import uvicorn
from aiogram import Bot

from src.api.app import create_app as create_fastapi_app
from src.core.bot import create_bot, setup_bot_commands
from src.core.config import get_settings
from src.core.dispatcher import create_dispatcher
from src.database.session import engine

logger = logging.getLogger(__name__)


def _register_graceful_shutdown(
    dispatcher,
    uvicorn_server: uvicorn.Server,
) -> None:
    """SIGINT/SIGTERM: останавливаем uvicorn и long polling (один event loop)."""

    loop = asyncio.get_running_loop()
    stop_once: dict[str, bool] = {"done": False}

    def _request_stop() -> None:
        logger.info("Получен сигнал остановки, завершаем uvicorn и long polling…")
        uvicorn_server.should_exit = True
        if stop_once["done"]:
            return
        stop_once["done"] = True
        asyncio.create_task(dispatcher.stop_polling())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            logger.debug("Пропуск add_signal_handler для сигнала %s (NotImplementedError)", sig)
        except RuntimeError as exc:
            logger.debug("Не удалось повесить обработчик %s: %s", sig, exc)


async def run_application() -> None:
    """Параллельно: uvicorn (FastAPI) + aiogram polling."""

    settings = get_settings()
    bot: Bot | None = None
    uvicorn_server: uvicorn.Server | None = None

    try:
        bot = create_bot()
        await setup_bot_commands(bot)
        dispatcher = create_dispatcher()
        
        from src.services.notification_service import NotificationService
        notification_service = NotificationService(bot, settings)
        dispatcher["notification_service"] = notification_service

        # Настройка продвинутого логирования
        from src.core.logger import setup_logger
        setup_logger(notification_service)

        fastapi_app = create_fastapi_app()

        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host=settings.http_host,
            port=settings.http_port,
            loop="asyncio",
            log_level="info",           # можно поставить "warning" чтобы было тише
            access_log=False,           # отключаем access log если не нужен
        )

        uvicorn_server = uvicorn.Server(uvicorn_config)
        _register_graceful_shutdown(dispatcher, uvicorn_server)

        async def run_bot() -> None:
            try:
                await dispatcher.start_polling(
                    bot,
                    handle_signals=False,
                    close_bot_session=False,
                )
            finally:
                if uvicorn_server:
                    uvicorn_server.should_exit = True

        from src.database.session import SessionFactory
        from src.core.in_review_stuck_monitor import run_in_review_stuck_monitor
        from src.core.archiver import run_archiver

        await asyncio.gather(
            uvicorn_server.serve(),
            run_bot(),
            # run_in_review_stuck_monitor(bot, SessionFactory),   # закомментировано, если спамит
            run_archiver(SessionFactory),
        )

    finally:
        from src.core.http_client import close_http_session

        if bot is not None:
            with suppress(Exception):
                await bot.session.close()
                logger.debug("Сессия Telegram закрыта")
        
        with suppress(Exception):
            await close_http_session()
        
        with suppress(Exception):
            await engine.dispose()
            logger.debug("Пул соединений SQLAlchemy освобождён")