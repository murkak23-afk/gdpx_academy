"""Silver Sakura — Шаблоны раскладок."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from src.core.cache.keyboard_cache import cached_keyboard
from src.presentation.common.base import PremiumBuilder


@cached_keyboard(ttl=3600)
def confirm_cancel_template(confirm_cb: Any, cancel_cb: Any, confirm_text: str = "Подтвердить") -> InlineKeyboardMarkup:
    """Стандартный шаблон: Подтверждение / Отмена."""
    return (PremiumBuilder()
            .primary(confirm_text, confirm_cb)
            .cancel(cancel_cb)
            .adjust(1)
            .as_markup())

@cached_keyboard(ttl=3600)
def back_only_template(back_cb: Any) -> InlineKeyboardMarkup:
    """Стандартный шаблон: Только кнопка Назад."""
    return (PremiumBuilder()
            .back(back_cb)
            .as_markup())
