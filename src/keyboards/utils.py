"""Silver Sakura — Утилиты для клавиатур."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

def create_row(*buttons: InlineKeyboardButton) -> list[InlineKeyboardButton]:
    return list(buttons)
