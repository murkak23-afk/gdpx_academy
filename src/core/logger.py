from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Union

from loguru import logger

if TYPE_CHECKING:
    from src.services.notification_service import NotificationService


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
        exception = record.get("exception")

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
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._notification_service.send_system_alert(
                        f"🚨 <b>Loguru ERROR:</b>\n\n{record['message']}"
                    )
                )
            except RuntimeError:
                pass


def setup_logger(notification_service: NotificationService | None = None) -> None:
    """
    Настраивает loguru: перехватывает стандартные логи, выводит в консоль и (опционально) в Telegram.
    """
    # 1. Очищаем дефолтные обработчики
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logging.INFO)

    # Устанавливаем обработчик для всех именованных логгеров (aiogram, sqlalchemy, etc)
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # 2. Настраиваем loguru
    config = {
        "handlers": [
            {
                "sink": sys.stderr,
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
                "level": "INFO",
            },
        ],
    }

    # 3. Если передан сервис уведомлений, добавляем Telegram Sink для ошибок
    # [!] ВРЕМЕННО ОТКЛЮЧЕНО ПО ПРОСЬБЕ ПОЛЬЗОВАТЕЛЯ (ИЗ-ЗА СПАМА О КОНФЛИКТАХ)
    # if notification_service:
    #     config["handlers"].append({
    #         "sink": TelegramNotificationSink(notification_service),
    #         "level": "ERROR",
    #         "filter": lambda record: record["level"].name in ["ERROR", "CRITICAL"],
    #     })

    logger.configure(**config)
    logger.info("Loguru logger initialized (with Telegram Sink if service provided)")
