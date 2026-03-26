from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.keyboards.constants import CALLBACK_INLINE_BACK, REPLY_BTN_BACK


def _inline_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]


def moderation_item_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки модерации для карточки pending."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Взять в работу",
                    callback_data=f"mod:take:{submission_id}",
                ),
                InlineKeyboardButton(
                    text="Reject",
                    callback_data=f"mod:reject:{submission_id}",
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
                    callback_data=f"mod:take_pick:{user_id}",
                )
            ],
            _inline_back_row(),
        ]
    )


def moderation_review_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Кнопки финального решения для карточки в работе."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Credit/Accepted",
                    callback_data=f"mod:accept:{submission_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Block",
                    callback_data=f"mod:block:{submission_id}",
                ),
                InlineKeyboardButton(
                    text="Not a scan",
                    callback_data=f"mod:notscan:{submission_id}",
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
                    text="Mark as paid",
                    callback_data=f"pay:mark:{user_id}",
                )
            ],
            _inline_back_row(),
        ]
    )


def search_report_keyboard(submission_id: int, seller_user_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопка открытия детального отчета по найденному товару."""

    row = [InlineKeyboardButton(text="Открыть отчёт", callback_data=f"admin:report_submission:{submission_id}")]
    rows = [row]
    if seller_user_id is not None:
        rows.append(
            [
                InlineKeyboardButton(text="Ограничить", callback_data=f"admin:restrict:{seller_user_id}"),
                InlineKeyboardButton(text="Снять ограничение", callback_data=f"admin:unrestrict:{seller_user_id}"),
            ]
        )
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_reject_template_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Шаблоны причин отклонения на первичной проверке."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Дубликат", callback_data=f"mod:rejtpl:{submission_id}:duplicate")],
            [InlineKeyboardButton(text="Низкое качество", callback_data=f"mod:rejtpl:{submission_id}:quality")],
            [InlineKeyboardButton(text="Нарушение правил", callback_data=f"mod:rejtpl:{submission_id}:rules")],
            [InlineKeyboardButton(text="Другое", callback_data=f"mod:rejtpl:{submission_id}:other")],
            [
                InlineKeyboardButton(
                    text=REPLY_BTN_BACK,
                    callback_data=f"mod:rejtpl_back:{submission_id}",
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
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page + 1}:{query}"))
    rows.append(nav)
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)
