from __future__ import annotations

import asyncio
import logging
import sys


def _configure_logging() -> None:
    """Настройка root-логгера: время, уровень, имя модуля, сообщение."""

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
    """Точка входа: FastAPI (uvicorn) + aiogram в одном event loop; SIGINT/SIGTERM — в `run_application`."""

    _configure_logging()
    log = logging.getLogger(__name__)
    log.info("Старт процесса (бот + HTTP)")
    try:
        # Импорт после настройки логов, чтобы цепочка импортов использовала root handler
        from src.core.app import run_application

        asyncio.run(run_application())
    except KeyboardInterrupt:
        log.info("Остановка по KeyboardInterrupt")
    finally:
        log.info("Процесс завершён")


if __name__ == "__main__":
    main()
