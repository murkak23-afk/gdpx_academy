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
        
        # Остановка ARQ
        arq_worker = getattr(dispatcher, "arq_worker", None)
        if arq_worker:
            arq_worker.abort()
        
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

    # Инициализация контента (FAQ, мануалы)
    from src.core.content_loader import init_content
    await init_content()

    settings = get_settings()
    
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastAPIIntegration
        from sentry_sdk.integrations.aiogram import AiogramIntegration
        
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=1.0,
            send_default_pii=False,
            integrations=[
                AsyncioIntegration(),
                FastAPIIntegration(),
                AiogramIntegration(),
            ],
        )
        logger.info("Sentry initialized")

    bot: Bot | None = None
    uvicorn_server: uvicorn.Server | None = None

    try:
        bot = create_bot()
        await setup_bot_commands(bot)
        dispatcher = create_dispatcher()
        
        from src.core.notification_service import NotificationService
        notification_service = NotificationService(bot, settings)
        dispatcher["notification_service"] = notification_service

        from src.core.logger import setup_logger
        setup_logger(notification_service)

        fastapi_app, ws_manager = create_fastapi_app(bot, dispatcher)
        dispatcher["ws_manager"] = ws_manager

        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host=settings.http_host,
            port=settings.http_port,
            loop="asyncio",
            log_level="info",
            access_log=True,
            log_config=None,  # Чтобы uvicorn не отключал наши кастомные логгеры
        )

        uvicorn_server = uvicorn.Server(uvicorn_config)
        _register_graceful_shutdown(dispatcher, uvicorn_server)

        is_production = settings.env.lower() == "production"

        async def run_bot() -> None:
            nonlocal is_production
            try:
                if is_production:
                    # Установка Webhook для продакшена
                    webhook_url = settings.webhook_url
                    logger.info(f"Setting webhook to {webhook_url}...")
                    try:
                        await bot.set_webhook(
                            url=webhook_url,
                            secret_token=settings.webhook_secret_token,
                            drop_pending_updates=True,
                            allowed_updates=dispatcher.resolve_used_update_types(),
                        )
                        logger.info("Webhook successfully set.")
                        # В режиме Webhook polling не нужен, просто ждем сигнала остановки
                        while not uvicorn_server.should_exit:
                            await asyncio.sleep(1)
                        return
                    except Exception as e:
                        logger.error(f"Failed to set webhook: {e}. Falling back to Long Polling!")
                        is_production = False # Переключаем флаг для корректного cleanup

                # Поллинг для разработки или если Webhook не удался
                logger.info("Starting long polling...")
                await dispatcher.start_polling(
                    bot,
                    handle_signals=False,
                    close_bot_session=False,
                )
            finally:
                if is_production:
                    logger.info("Deleting webhook...")
                    with suppress(Exception):
                        await bot.delete_webhook()
                
                if uvicorn_server:
                    uvicorn_server.should_exit = True

        from src.core.archiver import run_archiver
        from src.database.session import SessionFactory
        from arq.worker import create_worker
        from src.core.tasks import WorkerSettings
        
        async def run_arq_worker():
            try:
                worker = create_worker(WorkerSettings)
                dispatcher.arq_worker = worker # для graceful shutdown
                logger.info("ARQ Worker started.")
                await worker.main()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"ARQ Worker failed: {e}")

        await asyncio.gather(
            uvicorn_server.serve(),
            run_bot(),
            run_arq_worker(),
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
async def run_worker() -> None:
    """Запуск отдельного процесса ARQ worker."""
    from arq.worker import create_worker
    from src.core.tasks import WorkerSettings
    from src.core.config import get_settings
    
    settings = get_settings()
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.arq import ArqIntegration
        sentry_sdk.init(dsn=settings.sentry_dsn, integrations=[ArqIntegration()])

    logger.info("Starting standalone ARQ worker...")
    worker = create_worker(WorkerSettings)
    try:
        await worker.main()
    finally:
        await engine.dispose()
