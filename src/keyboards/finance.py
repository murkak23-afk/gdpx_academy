from __future__ import annotations
from datetime import datetime, timezone
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from src.callbacks.finance import FinancePayCD, FinanceTopupCD
from src.database.models.enums import PayoutStatus

def get_paylist_kb(sellers: list, page: int, total: int) -> InlineKeyboardMarkup:
    """Список продавцов, ожидающих выплату."""
    builder = InlineKeyboardBuilder()

    for seller in sellers:
        name = f"@{seller.username}" if seller.username else f"ID:{seller.telegram_id}"
        btn_text = f"💰 {name} | {seller.pending_balance} USDT"
        builder.button(
            text=btn_text,
            callback_data=FinancePayCD(action="user_detail", user_id=seller.id, page=page).pack()
        )

    builder.adjust(1)

    # Пагинация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=FinancePayCD(action="list", page=page-1).pack()))
    nav_row.append(InlineKeyboardButton(text=f"Стр. {page+1}", callback_data="ignore"))
    if (page + 1) * 10 < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=FinancePayCD(action="list", page=page+1).pack()))
    if nav_row:
        builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=FinancePayCD(action="list", page=page).pack()),
        InlineKeyboardButton(text="📜 ИСТОРИЯ", callback_data=FinancePayCD(action="history").pack())
    )
    builder.row(InlineKeyboardButton(text="📊 СТАТИСТИКА", callback_data=FinancePayCD(action="stats").pack()))
    
    return builder.as_markup()


def get_payout_confirm_kb(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Подтверждение создания выплаты."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ ПОДТВЕРДИТЬ И ВЫПЛАТИТЬ",
        callback_data=FinancePayCD(action="confirm", user_id=user_id, page=page).pack()
    )
    builder.button(
        text="❮ ОТМЕНА",
        callback_data=FinancePayCD(action="list", page=page).pack()
    )
    builder.adjust(1)
    return builder.as_markup()


def get_payout_history_kb(payouts: list, page: int, total: int, status_filter: str) -> InlineKeyboardMarkup:
    """Список истории выплат с фильтрами."""
    builder = InlineKeyboardBuilder()
    
    # Фильтры статусов
    filters = [
        ("📦 Все", "all"),
        ("🟢 PAID", "paid"),
        ("⏳ PEND", "pending"),
        ("🔴 CANC", "cancelled")
    ]
    filter_row = []
    for label, key in filters:
        text = f"▪️ {label}" if key == status_filter else label
        filter_row.append(InlineKeyboardButton(text=text, callback_data=FinancePayCD(action="history", filter_status=key).pack()))
    builder.row(*filter_row)

    for p in payouts:
        status_emoji = "🟢" if p.status == PayoutStatus.PAID else "⏳" if p.status == PayoutStatus.PENDING else "🔴"
        date_str = p.created_at.strftime("%d.%m")
        btn_text = f"{status_emoji} #{p.id} | {p.amount} USDT | {date_str}"
        builder.button(text=btn_text, callback_data=FinancePayCD(action="hist_detail", payout_id=p.id, page=page, filter_status=status_filter).pack())
    
    builder.adjust(4, 1, 1, 1, 1, 1, 1, 1, 1, 1)

    # Пагинация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=FinancePayCD(action="history", page=page-1, filter_status=status_filter).pack()))
    nav_row.append(InlineKeyboardButton(text=f"Стр. {page+1}", callback_data="ignore"))
    if (page + 1) * 10 < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=FinancePayCD(action="history", page=page+1, filter_status=status_filter).pack()))
    if nav_row:
        builder.row(*nav_row)

    builder.row(InlineKeyboardButton(text="❮ К РЕЕСТРУ", callback_data=FinancePayCD(action="list").pack()))
    return builder.as_markup()


def get_payout_detail_kb(payout_id: int, status: PayoutStatus, page: int, filter_status: str) -> InlineKeyboardMarkup:
    """Действия в карточке выплаты."""
    builder = InlineKeyboardBuilder()
    
    if status == PayoutStatus.PENDING:
        builder.button(text="❌ ОТМЕНИТЬ ВЫПЛАТУ", callback_data=FinancePayCD(action="undo_ask", payout_id=payout_id).pack())
    
    builder.button(text="❮ НАЗАД К ИСТОРИИ", callback_data=FinancePayCD(action="history", page=page, filter_status=filter_status).pack())
    builder.adjust(1)
    return builder.as_markup()


def get_payout_confirm_undo_kb(payout_id: int) -> InlineKeyboardMarkup:
    """Двойное подтверждение отмены."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ ДА, ВЕРНУТЬ ДЕНЬГИ", callback_data=FinancePayCD(action="undo_confirm", payout_id=payout_id).pack())
    builder.button(text="НЕТ, ОСТАВИТЬ", callback_data=FinancePayCD(action="hist_detail", payout_id=payout_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def get_finance_stats_kb() -> InlineKeyboardMarkup:
    """Кнопки в дашборде статистики."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 ОБНОВИТЬ", callback_data=FinancePayCD(action="stats").pack())
    builder.button(text="❮ К РЕЕСТРУ", callback_data=FinancePayCD(action="list").pack())
    builder.adjust(1)
    return builder.as_markup()
