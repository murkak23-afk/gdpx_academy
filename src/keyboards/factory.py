from __future__ import annotations

from typing import Optional
from aiogram.filters.callback_data import CallbackData

# --- Базовая навигация ---
class NavCD(CallbackData, prefix="nav"):
    to: str  # menu, profile, back, close
    page: int = 0

# --- СЕЛЛЕР ---
class SellerMenuCD(CallbackData, prefix="sel_menu"):
    action: str  # sell, profile, assets, payouts, info, support, faq, manuals

class SellerInfoCD(CallbackData, prefix="sel_info"):
    type: str # faq, manual_lvl, manual_item
    id: str = ""

class SellerAssetCD(CallbackData, prefix="sel_asset"):
    category_id: int
    page: int = 0
    filter_key: str = "all"

class SellerItemCD(CallbackData, prefix="sel_item"):
    item_id: int
    action: str  # view, edit, delete, delete_confirm

class SellerStatsCD(CallbackData, prefix="sel_stats"):
    period: str  # day, week, month, all

class SellerSettingsCD(CallbackData, prefix="sel_sett"):
    action: str  # main, pin, alias, incognito, prefs, lang, export, notif
    value: str = ""

class SellerNotifCD(CallbackData, prefix="sel_notif"):
    preference: str # full, summary, none

class PinPadCD(CallbackData, prefix="pin_pad"):
    action: str # digit, backspace, confirm, cancel
    value: str = ""
    context: str = "" # Например, 'payout', 'details'

class SellerSubmissionCD(CallbackData, prefix="sel_sub"):
    category_id: int
    action: str = "pick" # pick, cancel, finish

# --- АДМИН ---
class AdminMenuCD(CallbackData, prefix="adm_menu"):
    section: str  # queue, inwork, payouts, stats, broadcast, search

class AdminQueueCD(CallbackData, prefix="adm_q"):
    category_id: Optional[int] = None
    action: str = "list" # list, start, pick

class AdminInWorkCD(CallbackData, prefix="adm_iw"):
    seller_id: Optional[int] = None
    action: str = "list" # list, toggle, batch, search
    page: int = 0

class AdminPayoutCD(CallbackData, prefix="adm_pay"):
    user_id: int
    action: str # mark, confirm, final, cancel, trash
    page: int = 0

class AdminGradeCD(CallbackData, prefix="adm_grade"):
    item_id: int
    action: str # take, accept, not_scan, blocked, other

class CatConCD(CallbackData, prefix="catcon"):
    action: str # list, start, op, type, price, confirm, cancel, toggle, delete
    value: str = "" # Для хранения выбранного оператора или типа
    cat_id: int = 0

class CatManageCD(CallbackData, prefix="cat_manage"):
     action: str # view, toggle_active, toggle_priority, edit_price, confirm_delete, delete
     cat_id: int

# --- ВЛАДЕЛЕЦ (Управление пользователями) ---
class OwnerUserCD(CallbackData, prefix="ow_user"):
    action: str # list, view, role, status, balance, history, main
    user_id: int = 0
    role: str = "all" # all, seller, admin
    page: int = 0
