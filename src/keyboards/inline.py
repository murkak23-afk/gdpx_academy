from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.keyboards.callbacks import (
    CB_ADMIN_INWORK_HUB,
    CB_ADMIN_PAYOUTS,
    CB_ADMIN_QUEUE,
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_STATS_MONTH,
    CB_ADMIN_SEARCH_SIM,
    CB_ADMIN_UNRESTRICT,
    CB_GRADE_ACCEPT,
    CB_GRADE_BLOCKED,
    CB_GRADE_NOT_SCAN,
    CB_GRADE_OTHER,
    CB_GRADE_TAKE,
    CB_MOD_ACCEPT,
    CB_MOD_DEBIT,
    CB_MOD_HOLD_SELECT,
    CB_MOD_HOLD_SKIP,
    CB_MOD_REJECT,
    CB_MOD_REJTPL,
    CB_MOD_REJTPL_BACK,
    CB_MOD_TAKE,
    CB_MOD_TAKE_PICK,
    CB_ADMIN_BROADCAST,
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_FINAL_CONFIRM,
    CB_PAY_MARK,
    CB_PAY_TRASH,
    CB_SELLER_MENU_INFO,
    CB_SELLER_MENU_MATERIAL,
    CB_SELLER_MENU_PAYHIST,
    CB_SELLER_MENU_PROFILE,
    CB_SELLER_MENU_SELL,
    CB_SELLER_MENU_SUPPORT,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK, REPLY_BTN_BACK


# ─── Единый словарь меток кнопок ──────────────────────────────────────────
BTN_ADMIN_QUEUE         = "🗂 Буфер остатка"
BTN_ADMIN_INWORK        = "🛡 Операционная зона"
BTN_ADMIN_PAYOUTS       = "💸 Реестр выплат"
BTN_ADMIN_STATS_SIM     = "📊 Аналитика SIM"
BTN_ADMIN_BROADCAST     = "📢 Оповещение в BOT"
BTN_ADMIN_SEARCH_SIM    = "🔍 Поиск SIM"



BTN_MOD_TAKE            = "🔒 Взять в работу"
BTN_MOD_REPORT          = "🧾 Отчёт по SIM"
BTN_MOD_ACCEPT          = "◾️ Одобрить"
BTN_MOD_REJECT          = "▫️ Отклонить"



BTN_GRADE_ACCEPT        = "◾️ ЗАЧЕТ"
BTN_GRADE_NOT_SCAN      = "▫️ Отказ: Не скан"
BTN_GRADE_BLOCKED       = "▫️ Отказ: Блокировка"
BTN_GRADE_OTHER         = "▫️ Отказ: Иное"



BTN_PAY_MARK            = "💸 Исполнить транзакцию"
BTN_PAY_TRASH           = "✕ Аннулировать"
BTN_PAY_CONFIRM         = "◾️ Подтвердить перевод"
BTN_PAY_CANCEL          = "▫️ Отмена"
BTN_PAY_FINAL_CONFIRM   = "◾️ Отправить чек (CryptoBot)"



BTN_SEARCH_REPORT       = "🧾 Детали SIM"
BTN_RESTRICT            = "✕ Блокировать доступ"
BTN_UNRESTRICT          = "◾️ Восстановить доступ"


def _inline_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]


def admin_main_inline_keyboard(*, show_payout_finance: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=BTN_ADMIN_QUEUE, callback_data=CB_ADMIN_QUEUE)],
        [InlineKeyboardButton(text=BTN_ADMIN_INWORK, callback_data=CB_ADMIN_INWORK_HUB)],
        [
            InlineKeyboardButton(text=BTN_ADMIN_BROADCAST, callback_data=CB_ADMIN_BROADCAST),
            InlineKeyboardButton(text=BTN_ADMIN_SEARCH_SIM, callback_data=CB_ADMIN_SEARCH_SIM),
        ],
    ]
    if show_payout_finance:
        rows.insert(
            2,
            [
                InlineKeyboardButton(text=BTN_ADMIN_PAYOUTS, callback_data=CB_ADMIN_PAYOUTS),
                InlineKeyboardButton(text=BTN_ADMIN_STATS_SIM, callback_data=CB_ADMIN_STATS_MONTH),
            ],
        )
    else:
        rows.insert(2, [InlineKeyboardButton(text=BTN_ADMIN_PAYOUTS, callback_data=CB_ADMIN_PAYOUTS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seller_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Главное меню поставщика (Apple Style)"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⌲ Залить eSIM", callback_data=CB_SELLER_MENU_SELL)],
            [InlineKeyboardButton(text="🧑‍💻 Личный кабинет", callback_data=CB_SELLER_MENU_PROFILE)],
            [InlineKeyboardButton(text="🗂 Мои активы", callback_data=CB_SELLER_MENU_MATERIAL)],
            [
                InlineKeyboardButton(text="🧾 История выплат", callback_data=CB_SELLER_MENU_PAYHIST),
                InlineKeyboardButton(text="📜 Регламент", callback_data=CB_SELLER_MENU_INFO),
            ],
            [InlineKeyboardButton(text="🛎 Поддержка", callback_data=CB_SELLER_MENU_SUPPORT)],
        ]
    )


def moderation_item_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопка «Взять в работу» для pending-симки."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_MOD_TAKE,
                    callback_data=f"{CB_GRADE_TAKE}:{submission_id}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def grading_matrix_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Матрица оценки — одноклавишные вердикты после взятия симки в работу."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_GRADE_ACCEPT,
                    callback_data=f"{CB_GRADE_ACCEPT}:{submission_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BTN_GRADE_NOT_SCAN,
                    callback_data=f"{CB_GRADE_NOT_SCAN}:{submission_id}",
                ),
                InlineKeyboardButton(
                    text=BTN_GRADE_BLOCKED,
                    callback_data=f"{CB_GRADE_BLOCKED}:{submission_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BTN_GRADE_OTHER,
                    callback_data=f"{CB_GRADE_OTHER}:{submission_id}",
                ),
            ],
        ]
    )


def moderation_seller_group_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Выбор товаров продавца и пересылка в чат или ЛС."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Переслать выбранные (чат / ЛС)",
                    callback_data=f"{CB_MOD_TAKE_PICK}:{user_id}",
                )
            ],
            _inline_back_row(),
        ]
    )


def moderation_review_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки финального решения для симки в работе."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_MOD_REPORT,
                    callback_data=f"{CB_ADMIN_REPORT_SUBMISSION}:{submission_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BTN_MOD_ACCEPT,
                    callback_data=f"{CB_MOD_ACCEPT}:{submission_id}",
                ),
                InlineKeyboardButton(
                    text=BTN_MOD_REJECT,
                    callback_data=f"{CB_MOD_DEBIT}:{submission_id}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def payout_mark_paid_keyboard(user_id: int, *, ledger_page: int = 0) -> InlineKeyboardMarkup:
    """Кнопка фиксации выплаты пользователю (legacy; ведомость собирается в admin_menu)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_PAY_MARK,
                    callback_data=f"{CB_PAY_MARK}:{user_id}:{ledger_page}",
                ),
                InlineKeyboardButton(
                    text=BTN_PAY_TRASH,
                    callback_data=f"{CB_PAY_TRASH}:{user_id}:{ledger_page}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def payout_confirm_keyboard(user_id: int, *, ledger_page: int = 0) -> InlineKeyboardMarkup:
    """Подтверждение действия выплаты. ledger_page — для возврата к ведомости."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_PAY_CONFIRM,
                    callback_data=f"{CB_PAY_CONFIRM}:{user_id}:{ledger_page}",
                ),
                InlineKeyboardButton(
                    text=BTN_PAY_CANCEL,
                    callback_data=f"{CB_PAY_CANCEL}:{user_id}:{ledger_page}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def payout_final_confirm_keyboard(user_id: int, *, ledger_page: int = 0) -> InlineKeyboardMarkup:
    """Финальное подтверждение перед отправкой чека в CryptoBot."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_PAY_FINAL_CONFIRM,
                    callback_data=f"{CB_PAY_FINAL_CONFIRM}:{user_id}:{ledger_page}",
                ),
                InlineKeyboardButton(
                    text=BTN_PAY_CANCEL,
                    callback_data=f"{CB_PAY_CANCEL}:{user_id}:{ledger_page}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def search_report_keyboard(submission_id: int, seller_user_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопка открытия детального отчета по найденному товару."""

    row = [InlineKeyboardButton(text=BTN_SEARCH_REPORT, callback_data=f"{CB_ADMIN_REPORT_SUBMISSION}:{submission_id}")]
    rows = [row]
    if seller_user_id is not None:
        rows.append(
            [
                InlineKeyboardButton(text=BTN_RESTRICT, callback_data=f"{CB_ADMIN_RESTRICT}:{seller_user_id}"),
                InlineKeyboardButton(text=BTN_UNRESTRICT, callback_data=f"{CB_ADMIN_UNRESTRICT}:{seller_user_id}"),
            ]
        )
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_reject_template_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Шаблоны причин отклонения на первичной проверке."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Дублированние в системе", callback_data=f"{CB_MOD_REJTPL}:{submission_id}:duplicate")],
            [InlineKeyboardButton(text="Низкое качество", callback_data=f"{CB_MOD_REJTPL}:{submission_id}:quality")],
            [InlineKeyboardButton(text="Нарушение правил", callback_data=f"{CB_MOD_REJTPL}:{submission_id}:rules")],
            [InlineKeyboardButton(text="Другое", callback_data=f"{CB_MOD_REJTPL}:{submission_id}:other")],
            [
                InlineKeyboardButton(
                    text=REPLY_BTN_BACK,
                    callback_data=f"{CB_MOD_REJTPL_BACK}:{submission_id}",
                )
            ],
        ]
    )


def pagination_keyboard(prefix: str, page: int, total: int, page_size: int, query: str = "") -> InlineKeyboardMarkup:
    """Универсальная клавиатура пагинации."""

    max_page = (max(total, 1) - 1) // page_size
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{page - 1}:{query}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page + 1}:{query}"))
    rows.append(nav)
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hold_condition_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Выбор условия холда для переслана товара."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Моментально(БХ)", callback_data=f"{CB_MOD_HOLD_SELECT}:{submission_id}:no_hold")],
            [InlineKeyboardButton(text="15 минут", callback_data=f"{CB_MOD_HOLD_SELECT}:{submission_id}:15m")],
            [InlineKeyboardButton(text="30 минут", callback_data=f"{CB_MOD_HOLD_SELECT}:{submission_id}:30m")],
            [InlineKeyboardButton(text="Пропустить", callback_data=f"{CB_MOD_HOLD_SKIP}:{submission_id}")],
        ]
    )
