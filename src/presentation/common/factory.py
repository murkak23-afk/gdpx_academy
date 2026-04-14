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
    is_archived: bool = False

class SellerItemCD(CallbackData, prefix="sel_item"):
    item_id: int
    action: str  # view, edit, delete, delete_confirm

class SellerStatsCD(CallbackData, prefix="sel_stats"):
    period: str  # day, week, month, all

class SellerArchiveCD(CallbackData, prefix="sel_arch"):
    period: str # yesterday, 7d, 30d, all

class SellerSettingsCD(CallbackData, prefix="sel_sett"):
    action: str  # main, alias, incognito, prefs, lang, export, notif
    value: str = ""

class SellerNotifCD(CallbackData, prefix="sel_notif"):
    preference: str # full, summary, none

class SellerSubmissionCD(CallbackData, prefix="sel_sub"):
    category_id: int
    action: str = "pick" # pick, cancel, finish

class QRDeliveryCD(CallbackData, prefix="qr_deliv"):
    action: str # menu, op_list, op_pick, cancel
    val: str = ""

class LeaderboardCD(CallbackData, prefix="leaderboard"):
    period: str # all, 30d
    page: int = 0

class NotificationCD(CallbackData, prefix="notif"):
    action: str # close

# --- АДМИН ---
class AdminMenuCD(CallbackData, prefix="adm_menu"):
    section: str  # queue, inwork, payouts, stats, broadcast, search

class AdminQueueCD(CallbackData, prefix="adm_q"):
    category_id: Optional[int] = None
    item_id: Optional[int] = None
    action: str = "list" # list, start, pick, next, verification
    page: int = 0

class AdminSellerQueueCD(CallbackData, prefix="adm_sq"):
    user_id: Optional[int] = None
    action: str = "list" # list, view, toggle, apply, return_warehouse
    status: str = "pending" # pending, in_work, verification
    page: int = 0
    val: str = ""

class AdminSearchCD(CallbackData, prefix="adm_srch"):
    action: str = "filter" # filter, take_all
    filter_type: str = "all"
    query: str = ""

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
    action: str # take, accept, reject, block, not_scan, other, reason, cancel_defect
    val: str = ""

class CatConCD(CallbackData, prefix="catcon"):
    action: str # list, start, op, type, price, confirm, cancel, toggle, delete
    value: str = "" # Для хранения выбранного оператора или типа
    cat_id: int = 0

class CatManageCD(CallbackData, prefix="cat_manage"):
     action: str # view, toggle_active, toggle_priority, edit_price, confirm_delete, delete
     cat_id: int

class AutoFixConfirmCD(CallbackData, prefix="af_conf"):
    item_id: int
    status: str # blocked, not_a_scan
    action: str # confirm, cancel

# --- ВЛАДЕЛЕЦ (Управление пользователями) ---
class OwnerUserCD(CallbackData, prefix="ow_user"):
    action: str # list, view, role, status, balance, history, main
    user_id: int = 0
    role: str = "all" # all, seller, admin
    page: int = 0


class FinancePayCD(CallbackData, prefix="fin_pay"):
    action: str  # list, user_detail, confirm, cancel, history, hist_detail, stats, undo_ask, undo_confirm
    user_id: int = 0
    payout_id: int = 0
    page: int = 0
    filter_status: str = "all" # all, paid, pending, cancelled


class FinanceTopupCD(CallbackData, prefix="fin_top"):
    amount: float = 0.0
