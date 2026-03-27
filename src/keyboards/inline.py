from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.keyboards.callbacks import (
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_UNRESTRICT,
    CB_MOD_ACCEPT,
    CB_MOD_DEBIT,
    CB_MOD_REJECT,
    CB_MOD_REJTPL,
    CB_MOD_REJTPL_BACK,
    CB_MOD_TAKE,
    CB_MOD_TAKE_PICK,
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_MARK,
    CB_PAY_TRASH,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK, REPLY_BTN_BACK


def _inline_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]


def moderation_item_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки модерации для симки pending."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Взять в работу",
                    callback_data=f"{CB_MOD_TAKE}:{submission_id}",
                ),
                InlineKeyboardButton(
                    text="Reject",
                    callback_data=f"{CB_MOD_REJECT}:{submission_id}",
                ),
            ],
            _inline_back_row(),
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
                    text="Зачёт",
                    callback_data=f"{CB_MOD_ACCEPT}:{submission_id}",
                ),
                InlineKeyboardButton(
                    text="Незачёт",
                    callback_data=f"{CB_MOD_DEBIT}:{submission_id}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def payout_mark_paid_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Кнопка фиксации выплаты пользователю."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оплата",
                    callback_data=f"{CB_PAY_MARK}:{user_id}",
                ),
                InlineKeyboardButton(
                    text="В корзину",
                    callback_data=f"{CB_PAY_TRASH}:{user_id}",
                ),
            ],
            _inline_back_row(),
        ]
    )


def payout_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Подтверждение действия выплаты."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"{CB_PAY_CONFIRM}:{user_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"{CB_PAY_CANCEL}:{user_id}"),
            ],
            _inline_back_row(),
        ]
    )


def search_report_keyboard(submission_id: int, seller_user_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопка открытия детального отчета по найденному товару."""

    row = [InlineKeyboardButton(text="Открыть отчёт", callback_data=f"{CB_ADMIN_REPORT_SUBMISSION}:{submission_id}")]
    rows = [row]
    if seller_user_id is not None:
        rows.append(
            [
                InlineKeyboardButton(text="Ограничить", callback_data=f"{CB_ADMIN_RESTRICT}:{seller_user_id}"),
                InlineKeyboardButton(text="Снять ограничение", callback_data=f"{CB_ADMIN_UNRESTRICT}:{seller_user_id}"),
            ]
        )
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_reject_template_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Шаблоны причин отклонения на первичной проверке."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Дубликат", callback_data=f"{CB_MOD_REJTPL}:{submission_id}:duplicate")],
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
