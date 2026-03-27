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
CB_MOD_WORKED_TAB = "mod:worked_tab"
CB_MOD_WORKED_PAGE = "mod:worked_page"
CB_MOD_WORKED_EXPORT = "mod:worked_export"
CB_MOD_REJECT = "mod:reject"
CB_MOD_REJTPL = "mod:rejtpl"
CB_MOD_REJTPL_BACK = "mod:rejtpl_back"
CB_MOD_ACCEPT = "mod:accept"
CB_MOD_DEBIT = "mod:debit"

# Админ отчеты/поиск/статистика
CB_ADMIN_ARCHIVE_PAGE = "admin:archive_page"
CB_ADMIN_SEARCH_PAGE = "admin:search_page"
CB_ADMIN_RESTRICT = "admin:restrict"
CB_ADMIN_UNRESTRICT = "admin:unrestrict"
CB_ADMIN_REPORT_SUBMISSION = "admin:report_submission"
CB_ADMIN_STATS_VIEW = "admin:stats:view"
CB_ADMIN_STATS_PAGE = "admin:stats:pg"
CB_ADMIN_STATS_EXCEL = "admin:stats:excel"

# Запросы/категории/выплаты/капча
CB_REQ = "req"
CB_REQ_DELETE = "req:delete"
CB_REQ_CLEAR = "req:clear"
CB_REQ_CLEAR_CONFIRM = "req:clear_confirm"
CB_REQ_CLEAR_CANCEL = "req:clear_cancel"
CB_REQ_FACTORY_RESET = "req:factory_reset"
CB_REQ_FACTORY_CONFIRM = "req:factory_confirm"
CB_REQ_FACTORY_CANCEL = "req:factory_cancel"
CB_CAT = "cat"
CB_CAT_PICK_CATEGORY = "cat:pick"
CB_CAT_PICK_CATEGORY_PAGE = "cat:pick_page"
CB_PAY_MARK = "pay:mark"
CB_PAY_CONFIRM = "pay:confirm"
CB_PAY_CANCEL = "pay:cancel"
CB_PAY_TRASH = "pay:trash"
CB_PAY_HISTORY_PAGE = "pay:hist_page"
CB_PAY_TRASH_PAGE = "pay:trash_page"
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
