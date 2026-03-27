from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

import uvicorn
from aiogram import Bot

from src.api.app import create_app as create_fastapi_app
from src.core.bot import create_bot
from src.core.config import get_settings
from src.core.dispatcher import create_dispatcher
from src.core.in_review_stuck_monitor import run_in_review_stuck_monitor
from src.database.session import SessionFactory, engine

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
    """Параллельно: uvicorn (FastAPI) + aiogram polling; при остановке закрывает бота и пул БД."""

    settings = get_settings()
    bot: Bot | None = None
    uvicorn_server: uvicorn.Server | None = None

    try:
        bot = create_bot()
        dispatcher = create_dispatcher()

        fastapi_app = create_fastapi_app()
        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host=settings.http_host,
            port=settings.http_port,
            loop="asyncio",
            log_level="info",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        _register_graceful_shutdown(dispatcher, uvicorn_server)

        async def run_bot() -> None:
            try:
                asyncio.create_task(run_in_review_stuck_monitor(bot, SessionFactory))
                await dispatcher.start_polling(
                    bot,
                    handle_signals=False,
                    close_bot_session=False,
                )
            finally:
                uvicorn_server.should_exit = True

        await asyncio.gather(
            uvicorn_server.serve(),
            run_bot(),
        )
    finally:
        if bot is not None:
            with suppress(Exception):
                await bot.session.close()
                logger.debug("Сессия Telegram (aiohttp) закрыта")
        with suppress(Exception):
            await engine.dispose()
            logger.debug("Пул соединений SQLAlchemy освобождён")


async def run_polling() -> None:
    """Обратная совместимость: только бот без HTTP (тесты / узкий сценарий)."""

    bot: Bot | None = None
    try:
        bot = create_bot()
        dispatcher = create_dispatcher()

        def _request_stop() -> None:
            logger.info("Получен сигнал остановки, завершаем long polling…")
            asyncio.create_task(dispatcher.stop_polling())

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except NotImplementedError:
                logger.debug("Пропуск add_signal_handler для сигнала %s (NotImplementedError)", sig)
            except RuntimeError as exc:
                logger.debug("Не удалось повесить обработчик %s: %s", sig, exc)

        asyncio.create_task(run_in_review_stuck_monitor(bot, SessionFactory))
        await dispatcher.start_polling(
            bot,
            handle_signals=False,
            close_bot_session=False,
        )
    finally:
        if bot is not None:
            with suppress(Exception):
                await bot.session.close()
                logger.debug("Сессия Telegram (aiohttp) закрыта")
        with suppress(Exception):
            await engine.dispose()
            logger.debug("Пул соединений SQLAlchemy освобождён")
