"""Silver Sakura — Базовый построитель PremiumBuilder."""

from __future__ import annotations

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.presentation.common.constants import EMOJI_BACK, EMOJI_REFRESH, EMOJI_REJECT


class PremiumBuilder:
    """Универсальный построитель премиум-клавиатур."""

    def __init__(self):
        self.builder = InlineKeyboardBuilder()

    def button(self, text: str, callback_data: Any = None, url: str | None = None) -> PremiumBuilder:
        """Добавить обычную кнопку (callback или url)."""
        if isinstance(callback_data, CallbackData):
            callback_data = callback_data.pack()
        self.builder.button(text=text, callback_data=callback_data, url=url)
        return self

    def primary(self, text: str, callback_data: Any) -> PremiumBuilder:
        """Добавить главную (акцентную) кнопку."""
        return self.button(f"✨ {text}", callback_data)

    def danger(self, text: str, callback_data: Any) -> PremiumBuilder:
        """Добавить опасную (красную) кнопку."""
        return self.button(f"🛑 {text}", callback_data)

    def row(self, *buttons: InlineKeyboardButton) -> PremiumBuilder:
        """Добавить ряд кнопок."""
        self.builder.row(*buttons)
        return self

    def back(self, callback_data: Any, text: str = "Назад") -> PremiumBuilder:
        """Добавить кнопку назад."""
        if isinstance(callback_data, CallbackData):
            callback_data = callback_data.pack()
        self.builder.row(InlineKeyboardButton(text=f"{EMOJI_BACK} {text}", callback_data=callback_data))
        return self

    def cancel(self, callback_data: Any, text: str = "Отмена") -> PremiumBuilder:
        """Добавить кнопку отмены."""
        if isinstance(callback_data, CallbackData):
            callback_data = callback_data.pack()
        self.builder.row(InlineKeyboardButton(text=f"{EMOJI_REJECT} {text}", callback_data=callback_data))
        return self

    def refresh(self, callback_data: Any, text: str = "Обновить") -> PremiumBuilder:
        """Добавить кнопку обновления."""
        if isinstance(callback_data, CallbackData):
            callback_data = callback_data.pack()
        self.builder.row(InlineKeyboardButton(text=f"{EMOJI_REFRESH} {text}", callback_data=callback_data))
        return self

    def adjust(self, *sizes: int) -> PremiumBuilder:
        """Настроить сетку кнопок."""
        self.builder.adjust(*sizes)
        return self

    def pagination(self, prefix: str, page: int, total: int, page_size: int, query: str = "") -> PremiumBuilder:
        """Добавить ряд пагинации."""
        max_page = (max(total, 1) - 1) // page_size
        nav: list[InlineKeyboardButton] = []
        
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:p:{page - 1}:{query}"))
        
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"))
        
        if page < max_page:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:p:{page + 1}:{query}"))
        
        self.builder.row(*nav)
        return self

    def as_markup(self) -> InlineKeyboardMarkup:
        """Собрать и вернуть клавиатуру."""
        return self.builder.as_markup()
