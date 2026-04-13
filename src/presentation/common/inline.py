from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.cache.keyboard_cache import cached_keyboard
from src.presentation.common.constants import CALLBACK_INLINE_BACK, REPLY_BTN_BACK


def _inline_back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]

@cached_keyboard(ttl=300)
def pagination_keyboard(prefix: str, page: int, total: int, page_size: int, query: str = "") -> InlineKeyboardMarkup:
    """Универсальная клавиатура пагинации."""

    max_page = (max(total, 1) - 1) // page_size
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{page - 1}:{query}"))
    from src.presentation.callbacks import CB_NOOP
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page + 1}:{query}"))
    rows.append(nav)
    rows.append(_inline_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)
