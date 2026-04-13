"""Silver Sakura — Клавиатуры финансов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.presentation.common.factory import FinancePayCD, FinanceTopupCD
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.constants import *


def get_paylist_kb(sellers: list, page: int, total: int) -> InlineKeyboardMarkup:
    """Список селлеров, ожидающих выплаты."""
    builder = PremiumBuilder()
    
    for seller in sellers:
        name = f"@{seller.username}" if seller.username else f"ID:{seller.telegram_id}"
        builder.button(f"{EMOJI_FINANCE} {name} | {seller.pending_balance} USDT", 
                       FinancePayCD(action="user_detail", user_id=seller.id, page=page))
        
    builder.adjust(1)
    builder.pagination("fin_pay", page, total, 10)
    
    # Исправляем передачу bound methods в row()
    builder.row(
        InlineKeyboardButton(text=f"{EMOJI_REFRESH} ОБНОВИТЬ", callback_data=FinancePayCD(action="list", page=page).pack()),
        InlineKeyboardButton(text="📜 ИСТОРИЯ", callback_data=FinancePayCD(action="history").pack())
    )
    builder.row(
        InlineKeyboardButton(text="❮ НАЗАД В МЕНЮ", callback_data="owner_finance")
    )
    return builder.as_markup()

def get_payout_confirm_kb(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Подтверждение отправки выплаты."""
    return (PremiumBuilder()
            .primary("✅ ПОДТВЕРДИТЬ И ОТПРАВИТЬ", FinancePayCD(action="confirm", user_id=user_id, page=page))
            .cancel(FinancePayCD(action="list", page=page), "ОТМЕНИТЬ")
            .adjust(1)
            .as_markup())

def get_payout_history_kb(payouts: list, page: int, total: int, filter_status: str = "all") -> InlineKeyboardMarkup:
    """История всех транзакций/выплат."""
    builder = PremiumBuilder()
    
    # Фильтры
    statuses = [("ВСЕ", "all"), ("⏳ ОЖИДАЮТ", "pending"), ("✅ ВЫПЛАЧЕНО", "paid"), ("❌ ОТМЕНА", "cancelled")]
    for label, key in statuses:
        text = f"✨ {label}" if key == filter_status else label
        builder.button(text, FinancePayCD(action="history", filter_status=key, page=0))
    
    builder.adjust(2, 2)
    
    # Раньше здесь был цикл создания кнопок для каждой выплаты.
    # Теперь список выводится в тексте.
    
    builder.pagination("fin_hist", page, total, 10, query=filter_status)
    builder.back("owner_finance", "❮ НАЗАД В МЕНЮ")
    return builder.as_markup()

def get_payout_detail_kb(payout_id: int, status: str, page: int, filter_status: str) -> InlineKeyboardMarkup:
    """Детальный просмотр транзакции."""
    builder = PremiumBuilder()
    if status == "paid":
        builder.button("↩️ ОТМЕНИТЬ ВЫПЛАТУ (UNDO)", FinancePayCD(action="undo_ask", payout_id=payout_id, page=page, filter_status=filter_status))
    
    builder.back(FinancePayCD(action="history", page=page, filter_status=filter_status), "« К СПИСКУ")
    builder.adjust(1)
    return builder.as_markup()

def get_payout_confirm_undo_kb(payout_id: int) -> InlineKeyboardMarkup:
    """Подтверждение отмены уже выплаченной транзакции."""
    return (PremiumBuilder()
            .danger("⚠️ ДА, ВЕРНУТЬ НА БАЛАНС", FinancePayCD(action="undo_confirm", payout_id=payout_id))
            .cancel(FinancePayCD(action="hist_detail", payout_id=payout_id), "ОТМЕНИТЬ")
            .adjust(1)
            .as_markup())

def get_finance_stats_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата из статистики финансов."""
    return (PremiumBuilder()
            .back("owner_finance")
            .as_markup())

def get_topup_kb() -> InlineKeyboardMarkup:
    """Меню пополнения баланса (админское)."""
    builder = PremiumBuilder()
    amounts = [10, 50, 100, 250, 500]
    for amt in amounts:
        builder.button(f"➕ {amt} USDT", FinanceTopupCD(amount=float(amt)))
    builder.button(f"{EMOJI_PROFILE} СВОЯ СУММА", "topup_custom")
    builder.adjust(2, 2, 1, 1)
    builder.back("owner_finance")
    return builder.as_markup()
