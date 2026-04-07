"""Silver Sakura — Общие клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import TEXT_BACK

def get_back_kb(callback_data: Any) -> InlineKeyboardMarkup:
    return PremiumBuilder().back(callback_data).as_markup()

def get_cancel_kb(callback_data: Any) -> InlineKeyboardMarkup:
    return PremiumBuilder().cancel(callback_data).as_markup()
