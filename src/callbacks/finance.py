from __future__ import annotations
from aiogram.filters.callback_data import CallbackData

class FinancePayCD(CallbackData, prefix="fin_pay"):
    action: str  # list, user_detail, confirm, cancel, history, hist_detail, stats, undo_ask, undo_confirm
    user_id: int = 0
    payout_id: int = 0
    page: int = 0
    filter_status: str = "all" # all, paid, pending, cancelled

class FinanceTopupCD(CallbackData, prefix="fin_top"):
    amount: float = 0.0
