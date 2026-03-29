"""Точка входа: запускает Telegram-бот + HTTP-сервер (uvicorn/FastAPI).

Эквивалент ``python -m src``, но вызывается напрямую::

    python run.py

или через Makefile::

    make run

Все настройки берутся из переменных окружения / файла .env.

Частые проблемы при локальном запуске
--------------------------------------
1. «address already in use» (порт 8000) — другое приложение занимает порт.
   Решение: ``HTTP_PORT=8001`` в .env.local, либо убить процесс:
   ``fuser -k 8000/tcp``

2. Ошибка подключения к БД — ``POSTGRES_HOST`` в .env задан как ``postgres``
   (Docker-хост). Для локального запуска измени на ``localhost`` в .env.local.

3. «MemoryStorage» предупреждение — нормально для разработки.
   В продакшене задай ``REDIS_URL=redis://localhost:6379/0`` в .env.
"""

from __future__ import annotations

import asyncio
import logging
import sys


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)


def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)
    log.info("Запуск приложения (бот + HTTP)…")
    try:
        # Импорт после настройки логов — вся цепочка импортов использует root handler
        from src.core.app import run_application

        asyncio.run(run_application())
    except KeyboardInterrupt:
        log.info("Остановка по KeyboardInterrupt")
    finally:
        log.info("Процесс завершён")


if __name__ == "__main__":
    main()
