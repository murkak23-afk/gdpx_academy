"""Silver Sakura — Клавиатуры селлера."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *

def get_seller_main_kb() -> InlineKeyboardMarkup:
    """Главное меню селлера в стиле Silver Sakura."""
    return (PremiumBuilder()
            .button(f"{EMOJI_BOX} Залить eSIM", "seller_sell")
            .button(f"{EMOJI_ASSETS} Мои активы", "seller_assets")
            .button(f"{EMOJI_FINANCE} Выплаты/история", "seller_payouts")
            .button(f"{EMOJI_STATS} Статистика заработка", "seller_stats")
            .button(f"{EMOJI_KNOWLEDGE} База знаний", "seller_info")
            .button(f"{EMOJI_SUPPORT} Техническая поддержка", "seller_support")
            .button(f"{EMOJI_PROFILE} Профиль", "seller_profile")
            .adjust(1)
            .as_markup())

def get_seller_profile_kb() -> InlineKeyboardMarkup:
    """Профиль селлера (подменю)."""
    return (PremiumBuilder()
            .button(f"{EMOJI_LANTERN} Изменить псевдоним", "edit_pseudonym")
            .button(f"💳 Реквизиты выплат", "edit_payout_details")
            .adjust(1)
            .back("menu")
            .as_markup())
