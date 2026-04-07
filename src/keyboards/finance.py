"""Silver Sakura — Клавиатуры финансов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.callbacks.finance import FinancePayCD, FinanceTopupCD

def get_paylist_kb(sellers: list, page: int, total: int) -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    
    for seller in sellers:
        name = f"@{seller.username}" if seller.username else f"ID:{seller.telegram_id}"
        builder.button(f"{EMOJI_FINANCE} {name} | {seller.pending_balance} USDT", 
                       FinancePayCD(action="user_detail", user_id=seller.id, page=page))
        
    builder.adjust(1)
    builder.pagination("fin_pay", page, total, 10)
    
    builder.row(
        builder.builder.button(text=f"{EMOJI_REFRESH} ОБНОВИТЬ", callback_data=FinancePayCD(action="list", page=page).pack()).button,
        builder.builder.button(text="📜 ИСТОРИЯ", callback_data=FinancePayCD(action="history").pack()).button
    )
    return builder.as_markup()

def get_topup_kb() -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    amounts = [10, 50, 100, 250, 500]
    for amt in amounts:
        builder.button(f"➕ {amt} USDT", FinanceTopupCD(amount=float(amt)))
    builder.button(f"{EMOJI_PROFILE} СВОЯ СУММА", "topup_custom")
    builder.adjust(2, 2, 1, 1)
    builder.back("admin_menu")
    return builder.as_markup()
