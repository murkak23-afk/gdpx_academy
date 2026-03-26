from __future__ import annotations

from aiogram import Bot

from src.core.bot import create_bot
from src.core.dispatcher import create_dispatcher


async def run_polling() -> None:
    """Запускает long polling бота."""

    bot: Bot = create_bot()
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)
