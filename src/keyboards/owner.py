"""Silver Sakura — Клавиатуры владельца (Owner/Admin)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *

def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Главное меню администратора (Terminal Style)."""
    return (PremiumBuilder()
            .primary("⚖️ МОДЕРАЦИЯ", "admin_moderation")
            .button(f"{EMOJI_LANTERN} Управление кластерами", "admin_categories")
            .button(f"{EMOJI_FINANCE} Финансовый реестр", "admin_finance")
            .button(f"{EMOJI_SEARCH} Глобальный поиск", "admin_search")
            .button(f"{EMOJI_STATS} Системная аналитика", "admin_stats")
            .adjust(1)
            .as_markup())
