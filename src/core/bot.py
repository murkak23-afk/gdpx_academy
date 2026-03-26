from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.core.config import get_settings


def _resolve_parse_mode(raw_value: str) -> ParseMode:
    """Преобразует строку из env в допустимый ParseMode."""

    normalized = raw_value.strip().upper()
    if normalized == "MARKDOWN":
        return ParseMode.MARKDOWN
    if normalized == "MARKDOWN_V2":
        return ParseMode.MARKDOWN_V2
    return ParseMode.HTML


def create_bot() -> Bot:
    """Создаёт и возвращает экземпляр Telegram-бота."""

    settings = get_settings()
    parse_mode = _resolve_parse_mode(settings.bot_parse_mode)
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=parse_mode),
    )
