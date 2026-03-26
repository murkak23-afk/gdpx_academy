from __future__ import annotations

import asyncio
import logging

from src.core.app import run_polling


def main() -> None:
    """Точка входа запуска Telegram-бота."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
