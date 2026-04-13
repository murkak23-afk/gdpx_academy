"""Reusable inline paginator for aiogram 3.x.

Использование — 4 строки в любом хендлере:

    page = InlinePaginator(
        items=my_list,
        page_size=8,
        page=current_page,
        callback_prefix=CB_MY_PAGE,
    )
    # Встроить навигацию в клавиатуру:
    kb = page.inject(existing_rows)
    # Получить срез элементов на текущей странице:
    for item in page.items_on_page():
        ...

Навигационная строка:  [◀]  2 / 5  [▶]
Центральный элемент:   кнопка CB_NOOP (тап — без действия).
Одна страница:         навигационная строка не добавляется.

────────────────────────────────────
Передача page из callback:
────────────────────────────────────
    # Регистрация callback:
    CB_SELLERS_PAGE = "sellers_page"

    @router.callback_query(F.data.startswith(CB_SELLERS_PAGE + ":"))
    async def on_page(callback: CallbackQuery, ...) -> None:
        page_num = int(callback.data.split(":", 1)[1])
        paginator = InlinePaginator(items=all_items, page_size=8, page=page_num, callback_prefix=CB_SELLERS_PAGE)
        ...
"""

from __future__ import annotations

from math import ceil
from typing import TypeVar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.presentation.callbacks import CB_NOOP

T = TypeVar("T")

# Символы по умолчанию — можно переопределить через параметры
_PREV = "◀"
_NEXT = "▶"


class InlinePaginator(list):
    """Typed list with built-in pagination metadata and keyboard injection.

    Наследуем list, поэтому объект сам является срезом текущей страницы
    (удобно в for-циклах) и при этом хранит метаданные навигации.
    """

    def __init__(
        self,
        items: list[T],
        *,
        page_size: int,
        page: int,
        callback_prefix: str,
        prev_label: str = _PREV,
        next_label: str = _NEXT,
    ) -> None:
        self.total       = len(items)
        self.page_size   = max(page_size, 1)
        self.max_page    = max(ceil(self.total / self.page_size) - 1, 0) if self.total else 0
        self.page        = min(max(page, 0), self.max_page)
        self._prefix     = callback_prefix
        self._prev_label = prev_label
        self._next_label = next_label

        start = self.page * self.page_size
        super().__init__(items[start : start + self.page_size])

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page < self.max_page

    @property
    def needs_navigation(self) -> bool:
        return self.max_page > 0

    def page_label(self) -> str:
        return f"{self.page + 1} / {self.max_page + 1}"

    # ── Keyboard helpers ──────────────────────────────────────────────────

    def nav_row(self) -> list[InlineKeyboardButton]:
        """
        Builds the terminal navigation row.
        Пример: [ ◄ ]  [ 02 / 05 ]  [ ► ]
        """
        row: list[InlineKeyboardButton] = []

        # Задаем строгие геометрические векторы
        nav_prev = "◄" 
        nav_next = "►"

        if self.has_prev:
            row.append(InlineKeyboardButton(
                text=nav_prev,
                callback_data=f"{self._prefix}:{self.page - 1}",
            ))
        else:
            # Оставляем пустой слот для центровки
            row.append(InlineKeyboardButton(text=" ", callback_data=CB_NOOP))

        # Оборачиваем индикатор страниц в терминальные скобки
        # Идеально, если self.page_label() отдает формат "01 / 05"
        center_text = f"[ {self.page_label()} ]"
        row.append(InlineKeyboardButton(text=center_text, callback_data=CB_NOOP))

        if self.has_next:
            row.append(InlineKeyboardButton(
                text=nav_next,
                callback_data=f"{self._prefix}:{self.page + 1}",
            ))
        else:
            row.append(InlineKeyboardButton(text=" ", callback_data=CB_NOOP))

        return row

    def inject(
        self,
        rows: list[list[InlineKeyboardButton]],
        *,
        position: int = -1,
    ) -> InlineKeyboardMarkup:
        """Inserts the navigation row into ``rows`` and returns an InlineKeyboardMarkup.

        ``position``: index where to insert the nav row.
        -1  → before the last row (default — back button last)
         0  → at the top
        ``len(rows)`` → at the bottom
        """
        result = [list(r) for r in rows]
        if self.needs_navigation:
            nav = self.nav_row()
            if position < 0:
                insert_at = max(len(result) + position + 1, 0)
            else:
                insert_at = min(position, len(result))
            result.insert(insert_at, nav)
        return InlineKeyboardMarkup(inline_keyboard=result)

    def keyboard(self, extra_rows: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
        """Return a keyboard with ONLY the navigation row + optional extra rows."""
        rows: list[list[InlineKeyboardButton]] = []
        if self.needs_navigation:
            rows.append(self.nav_row())
        if extra_rows:
            rows.extend(extra_rows)
        return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Standalone factory (альтернативный стиль) ─────────────────────────────


def paginate(
    items: list[T],
    *,
    page: int,
    page_size: int,
    callback_prefix: str,
) -> "InlinePaginator[T]":
    """Functional alias — ``paginate(items, page=p, page_size=8, callback_prefix=CB_X)``."""
    return InlinePaginator(items, page_size=page_size, page=page, callback_prefix=callback_prefix)
