"""Единые соглашения по callback_data.

Формат: <scope>:<action>[:arg1[:arg2...]]
- scope: mod | admin | req | cat | pay | nav | noop | captcha
- разделители только ":" (кроме уже существующих query-параметров внутри значений)
"""

from __future__ import annotations

# Общие
CB_NOOP = "noop"

# Навигация
CB_NAV_INLINE_BACK = "nav:inline_back"

# Модерация
CB_MOD_TAKE = "mod:take"
CB_MOD_TAKE_PICK = "mod:take_pick"
CB_MOD_PICK_CANCEL = "mod:pick_cancel"
CB_MOD_FORWARD_CANCEL = "mod:forward_cancel"
CB_MOD_BATCH_ACTION = "mod:batch_action"
CB_MOD_BATCH_CONFIRM = "mod:batch_confirm"
CB_MOD_BATCH_CANCEL = "mod:batch_cancel"
CB_MOD_FORWARD_CONFIRM = "mod:forward_confirm"
CB_MOD_FORWARD_CONFIRM_CANCEL = "mod:forward_confirm_cancel"
CB_MOD_QUEUE_PAGE = "mod:queue_page"
CB_MOD_IN_REVIEW_PAGE = "mod:in_review_page"
CB_MOD_REJECT = "mod:reject"
CB_MOD_REJTPL = "mod:rejtpl"
CB_MOD_REJTPL_BACK = "mod:rejtpl_back"
CB_MOD_ACCEPT = "mod:accept"
CB_MOD_DEBIT = "mod:debit"
CB_MOD_HOLD_SELECT = "mod:hold_select"
CB_MOD_HOLD_SKIP = "mod:hold_skip"

# Админ отчеты/поиск/статистика
CB_ADMIN_ARCHIVE_PAGE = "admin:archive_page"
CB_ADMIN_SEARCH_PAGE = "admin:search_page"
CB_ADMIN_RESTRICT = "admin:restrict"
CB_ADMIN_UNRESTRICT = "admin:unrestrict"
CB_ADMIN_REPORT_SUBMISSION = "admin:report_submission"
CB_ADMIN_INWORK_SEARCH = "admin:inwork_search"
CB_ADMIN_INWORK_OPEN = "admin:inwork_open"
CB_ADMIN_QUEUE = "admin:queue"
CB_ADMIN_QUEUE_START = "admin:queue_start"
CB_ADMIN_QUEUE_SEARCH = "admin:queue:search"
CB_ADMIN_QUEUE_FILTER_CAT = "admin:queue:filter_cat"
CB_ADMIN_QUEUE_PAGE = "admin:queue:page"
CB_ADMIN_INWORK_HUB = "admin:inwork_hub"
CB_ADMIN_PAYOUTS = "admin:payouts"
CB_ADMIN_BROADCAST = "admin:broadcast"
CB_ADMIN_ARCHIVE = "admin:archive"

# Категории/выплаты/капча
CB_PAY_MARK = "pay:mark"
CB_PAY_CONFIRM = "pay:confirm"
CB_PAY_FINAL_CONFIRM = "pay:final_confirm"
CB_PAY_TOPUP = "pay:topup"
CB_PAY_TOPUP_CHECK = "pay:topup_check"
CB_PAY_CANCEL = "pay:cancel"
CB_PAY_TRASH = "pay:trash"
CB_PAY_HISTORY_PAGE = "pay:hist_page"
CB_PAY_TRASH_PAGE = "pay:trash_page"
CB_PAY_LEDGER_PAGE = "pay:ledger_page"
CB_PAY_PENDING_PAGE = "pay:pending_page"
CB_PAY_PENDING_DELETE = "pay:pending_delete"
CB_ADMIN_INWORK_PAGE = "admin:inwork_page"
CB_CAPTCHA_START = "captcha:start"
CB_CAPTCHA_CANCEL = "captcha:cancel"

# Seller: material and payouts history
CB_SELLER_MAT_CAT = "seller:mat:cat"
CB_SELLER_MAT_PAGE = "seller:mat:page"
CB_SELLER_MAT_ITEM = "seller:mat:item"
CB_SELLER_MAT_EDIT = "seller:mat:edit"
CB_SELLER_MAT_DELETE = "seller:mat:delete"
CB_SELLER_MAT_DELETE_CONFIRM = "seller:mat:delete_confirm"
CB_SELLER_MAT_EDIT_MEDIA = "seller:mat:edit_media"
CB_SELLER_MAT_BACK = "seller:mat:back"
CB_SELLER_MAT_FILTER = "seller:mat:filter"
CB_SELLER_PAYHIST_PAGE = "seller:payhist:page"
CB_SELLER_STATS_VIEW = "seller:stats:view"
CB_SELLER_INFO_ROOT = "seller:info:root"
CB_SELLER_INFO_FAQ = "seller:info:faq"
CB_SELLER_INFO_MANUALS = "seller:info:manuals"
CB_SELLER_MENU_PROFILE = "seller:menu:profile"
CB_SELLER_MENU_SELL = "seller:menu:sell"
CB_SELLER_MENU_QUICK_ADD = "seller:menu:quick_add"
CB_SELLER_MENU_STATS = "seller:menu:stats"
CB_SELLER_MENU_MATERIAL = "seller:menu:material"
CB_SELLER_MENU_PAYHIST = "seller:menu:payhist"
CB_SELLER_MENU_INFO = "seller:menu:info"
CB_SELLER_MENU_SUPPORT = "seller:menu:support"
CB_SELLER_CANCEL_FSM = "seller:cancel_fsm"
CB_SELLER_FINISH_BATCH = "seller:finish_batch"
CB_SELLER_BATCH_SEND = "seller:batch:send"
CB_SELLER_BATCH_REJECT = "seller:batch:reject"
CB_SELLER_BATCH_CSV_YES = "seller:batch:csv_yes"
CB_SELLER_BATCH_CSV_NO = "seller:batch:csv_no"
CB_SELLER_FSM_CAT = "seller:fsm:cat"

# Поиск симки (админ)
CB_ADMIN_SEARCH_SIM = "admin:search_sim"

# Матрица оценки (Grading Matrix)
CB_GRADE_TAKE = "grade:take"
CB_GRADE_ACCEPT = "grade:accept"
CB_GRADE_NOT_SCAN = "grade:not_scan"
CB_GRADE_BLOCKED = "grade:blocked"
CB_GRADE_OTHER = "grade:other"

# Конструктор категорий
CB_CATCON_OPERATOR = "catcon:op"
CB_CATCON_TYPE = "catcon:type"
CB_CATCON_HOLD = "catcon:hold"
CB_CATCON_CONFIRM = "catcon:confirm"
CB_CATCON_CANCEL = "catcon:cancel"
CB_CATCON_LIST = "catcon:list"
CB_CATCON_TOGGLE = "catcon:toggle"
CB_CATCON_DETAIL = "catcon:detail"
CB_CATCON_EDIT = "catcon:edit"
CB_CATCON_DELETE = "catcon:del"
CB_CATCON_DELETE_YES = "catcon:del_yes"
CB_CATCON_FORCE_DELETE_YES = "catcon:del_force"
