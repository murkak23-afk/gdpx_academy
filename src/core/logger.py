from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Union

import random
from loguru import logger
from src.core.config import get_settings

if TYPE_CHECKING:
    from src.core.notification_service import NotificationService


class InterceptHandler(logging.Handler):
    """
    Стандартный обработчик для перехвата логов из модуля logging и перенаправления их в loguru.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Получаем соответствующий уровень loguru
        try:
            level: Union[str, int] = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Находим вызывающий код
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class TelegramNotificationSink:
    """
    Кастомный Sink для Loguru, который отправляет ошибки уровня ERROR и выше в Telegram.
    """

    def __init__(self, notification_service: NotificationService) -> None:
        self._notification_service = notification_service

    def __call__(self, message: Any) -> None:
        # Извлекаем данные из сообщения loguru
        record = message.record
        msg_text = str(record["message"]).lower()
        
        # ЗАЩИТА ОТ РЕКУРСИИ: если ошибка связана с сетью/Telegram, не шлем алерт
        if any(x in msg_text for x in ["timeout", "resolution", "retry after", "network error", "connector"]):
            return

        exception = record.get("exception")
        
        # Если есть исключение — проверяем и его текст
        if exception:
            exc_str = str(exception.value).lower()
            if any(x in exc_str for x in ["timeout", "resolution", "retry after", "network error", "connector"]):
                return

        # Если есть исключение — отправляем детальный отчет
        if exception:
            import asyncio
            # Создаем таск в текущем event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._notification_service.notify_critical_error(
                        exc=exception.value,
                        update_id=None,
                        user_id=None
                    )
                )
            except RuntimeError:
                # Вне event loop (например, при запуске/остановке)
                pass
        else:
            # Если это просто лог уровня ERROR без исключения
            import asyncio
            from html import escape
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._notification_service.send_system_alert(
                        f"🚨 <b>Loguru ERROR:</b>\n\n{escape(str(record['message']))}"
                    )
                )
            except RuntimeError:
                pass


def setup_logger(notification_service: NotificationService | None = None) -> None:
    """
    Настраивает loguru: перехватывает стандартные логи, выводит в консоль и (опционально) в Telegram.
    """
    settings = get_settings()
    is_prod = settings.env == "production"
    
    # 1. Очищаем дефолтные обработчики
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Устанавливаем обработчик для всех именованных логгеров (aiogram, sqlalchemy, etc)
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # Фильтр для сэмплинга логов в продакшене
    def sampling_filter(record):
        if is_prod and record["level"].name == "INFO":
            # Пропускаем только 10% INFO сообщений
            return random.random() < 0.1
        return True

    # 2. Настраиваем loguru
    config = {
        "handlers": [
            {
                "sink": sys.stderr,
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
                "level": settings.log_level.upper(),
                "filter": sampling_filter if is_prod else None,
            },
        ],
    }

    # 3. Если передан сервис уведомлений, добавляем Telegram Sink для ошибок
    if notification_service and is_prod:
         config["handlers"].append({
             "sink": TelegramNotificationSink(notification_service),
             "level": "ERROR",
             "filter": lambda record: record["level"].name in ["ERROR", "CRITICAL"],
         })

    logger.configure(**config)
    logger.info(f"Loguru logger initialized (Level: {settings.log_level}, Prod sampling: {is_prod})")
