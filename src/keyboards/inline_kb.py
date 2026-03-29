"""Inline-клавиатуры для пользовательского (seller) интерфейса магазина.

Этот модуль — удобная точка входа для всех inline-кнопок, которые видит
обычный пользователь (продавец). Не дублирует существующий inline.py,
а реэкспортирует нужные клавиатуры и добавляет специфику «магазина»:
выбор категории из БД-данных и навигация по страницам материалов.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.keyboards.callbacks import (
    CB_SELLER_FSM_CAT,
    CB_SELLER_MAT_PAGE,
    CB_SELLER_MENU_INFO,
    CB_SELLER_MENU_MATERIAL,
    CB_SELLER_MENU_PAYHIST,
    CB_SELLER_MENU_PROFILE,
    CB_SELLER_MENU_QUICK_ADD,
    CB_SELLER_MENU_SELL,
    CB_SELLER_MENU_SUPPORT,
)

# Реэкспорт из основного модуля — используй эти имена напрямую из inline_kb
from src.keyboards.inline import (
    moderation_item_keyboard,
    moderation_reject_template_keyboard,
    moderation_review_keyboard,
    payout_confirm_keyboard,
    payout_mark_paid_keyboard,
    seller_main_inline_keyboard,
)
from src.keyboards.constants import REPLY_BTN_BACK, CALLBACK_INLINE_BACK

__all__ = [
    # реэкспорт
    "seller_main_inline_keyboard",
    "moderation_item_keyboard",
    "moderation_review_keyboard",
    "moderation_reject_template_keyboard",
    "payout_mark_paid_keyboard",
    "payout_confirm_keyboard",
    # специфика магазина
    "seller_menu_keyboard",
    "categories_inline_keyboard",
    "my_materials_nav_keyboard",
    "cancel_keyboard",
]


def seller_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню продавца.

    Алиас для ``seller_main_inline_keyboard()`` — удобен при импорте из inline_kb.
    """
    return seller_main_inline_keyboard()


def categories_inline_keyboard(
    categories: list[tuple[int, str]],
    *,
    per_row: int = 2,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора категории/оператора.

    Args:
        categories: список пар (category_id, title), например из БД.
        per_row: сколько кнопок в строке (по умолчанию 2).

    Пример использования::

        cats = [(c.id, c.title) for c in await get_active_categories()]
        await message.answer("Выбери категорию:", reply_markup=categories_inline_keyboard(cats))
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for cat_id, title in categories:
        row.append(
            InlineKeyboardButton(
                text=title,
                callback_data=f"{CB_SELLER_FSM_CAT}:{cat_id}",
            )
        )
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # кнопка «Назад» в конце
    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_materials_nav_keyboard(
    *,
    page: int,
    total_pages: int,
    filter_key: str = "all",
) -> InlineKeyboardMarkup:
    """Навигационная клавиатура для списка материалов пользователя.

    Показывает стрелки «‹» / «›» только если есть соответствующие страницы.
    """
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="‹",
                callback_data=f"{CB_SELLER_MAT_PAGE}:{filter_key}:{page - 1}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{max(total_pages, 1)}",
            callback_data="noop",
        )
    )
    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="›",
                callback_data=f"{CB_SELLER_MAT_PAGE}:{filter_key}:{page + 1}",
            )
        )
    back_row = [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]
    return InlineKeyboardMarkup(inline_keyboard=[nav_row, back_row])


def cancel_keyboard(cancel_callback: str = "noop") -> InlineKeyboardMarkup:
    """Минимальная клавиатура с одной кнопкой «Отмена».

    Удобна во время FSM-диалогов, когда нужно дать выход без back-стека.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_callback)]
        ]
    )
