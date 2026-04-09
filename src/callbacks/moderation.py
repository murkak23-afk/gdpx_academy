from __future__ import annotations
from typing import Optional
from aiogram.filters.callback_data import CallbackData

class AdminQueueCD(CallbackData, prefix="mod_q"):
    action: str  # start, list, stats

class AdminGradeCD(CallbackData, prefix="mod_g"):
    item_id: int
    action: str  # accept, reject, not_scan, block, take, cancel_defect, undo, reason
    val: str = "" # Для передачи причины или комментария

class AdminBatchCD(CallbackData, prefix="mod_b"):
    action: str   # start, toggle, apply, status, reason, cancel, select_all, clear
    val: str = "" # Универсальное поле (ID, страница, статус и т.д.)

class AdminSellerQueueCD(CallbackData, prefix="mod_sel"):
    user_id: int = 0
    action: str  # list, view, take_all, take_5, take_10 и т.д.

class AdminSearchCD(CallbackData, prefix="mod_src"):
    action: str                    # filter, take_all
    filter_type: str = "all"       # all, prio, sla8, sla15
    query: str = ""

class SimQueueCD(CallbackData, prefix="sim_q"):
    action: str  # cat, qty
    cat_id: int = 0
    val: str = ""    