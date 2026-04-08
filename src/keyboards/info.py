"""Silver Sakura — Клавиатуры информационного центра (FAQ, Мануалы)."""

from __future__ import annotations

from typing import Iterable, Any
from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.keyboards.factory import NavCD, SellerMenuCD, SellerInfoCD

def get_info_root_kb(chat_url: str | None = None) -> InlineKeyboardMarkup:
    """Главный экран информационного центра (База Знаний)."""
    builder = PremiumBuilder()
    
    # Большая кнопка сверху (ссылка на чат)
    if chat_url:
        builder.button("💬 GDPX // ACADEMY", url=chat_url)
    
    # Основные кнопки раздела
    builder.button(f"{EMOJI_KNOWLEDGE} F.A.Q.", SellerMenuCD(action="faq"))
    builder.button(f"🧭 МАНУАЛЫ", SellerMenuCD(action="manuals"))
    
    builder.adjust(1, 2)
    builder.back("mod_exit", "В ГЛАВНОЕ МЕНЮ")
    return builder.as_markup()

def get_faq_list_kb(faq_cards: list) -> InlineKeyboardMarkup:
    """Список вопросов FAQ."""
    builder = PremiumBuilder()
    for f in faq_cards:
        builder.button(f"{f.emoji} {f.title}", SellerInfoCD(type="faq", id=f.id))
    builder.adjust(1)
    builder.back(SellerMenuCD(action="info"), "В INFO-ЦЕНТР")
    return builder.as_markup()

def get_manual_levels_kb(manual_levels: Iterable[Any]) -> InlineKeyboardMarkup:
    """Список уровней мануалов."""
    builder = PremiumBuilder()
    for lvl in manual_levels:
        builder.button(f"{lvl.emoji} {lvl.title}", SellerInfoCD(type="manual_lvl", id=lvl.id))
    builder.adjust(1)
    builder.back(SellerMenuCD(action="info"), "В INFO-ЦЕНТР")
    return builder.as_markup()

def get_manuals_in_level_kb(manuals: list[Any]) -> InlineKeyboardMarkup:
    """Список мануалов в конкретном уровне."""
    builder = PremiumBuilder()
    for m in manuals:
        builder.button(f"{m.emoji} {m.title}", SellerInfoCD(type="manual_item", id=m.id))
    builder.adjust(1)
    builder.back(SellerMenuCD(action="manuals"), "К УРОВНЯМ")
    return builder.as_markup()

def get_back_to_manual_level_kb(level_id: str) -> InlineKeyboardMarkup:
    """Кнопка возврата к списку мануалов уровня."""
    return (PremiumBuilder()
            .back(SellerInfoCD(type="manual_lvl", id=level_id))
            .as_markup())

def get_back_to_info_kb(type: str) -> InlineKeyboardMarkup:
    """Кнопка возврата в FAQ или Мануалы."""
    back_action = "faq" if type == "faq" else "manuals"
    return (PremiumBuilder()
            .back(SellerMenuCD(action=back_action))
            .as_markup())
