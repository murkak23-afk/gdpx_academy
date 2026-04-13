"""Text-formatting utilities for GDPX Telegram UI.

Все хелперы возвращают HTML-строки (parse_mode='HTML').
Ни один хелпер не меняет смысл данных — только представление.

──────────────────────────────────────────────────
Быстрый чит-лист
──────────────────────────────────────────────────
    format_currency(10500)         → "<code>10 500.00</code> USDT"
    format_currency(10500, "₽")   → "<code>10 500.00</code> ₽"
    format_currency(10500, sign="$", before=True) → "<code>$ 10 500.00</code>"

    format_mono("+79001234567")    → "<code>+79001234567</code>"
    format_mono("0x1A2B…")        → "<code>0x1A2B…</code>"   (кошелёк)

    format_status(True)            → "🟢"
    format_status(False)           → "🔴"
    format_status("accepted")      → "◾️"   (ключ из STATUS_MAP)
    format_status("pending")       → "⏳"

    format_count(42)               → "<code>42</code>"
    format_count(42, "шт.")        → "<code>42</code> шт."

    format_number(1234567.89)      → "1 234 567.89"   # без тегов

    format_bold(text)              → "<b>text</b>"
    format_italic(text)            → "<i>text</i>"

    esc(text)                      → html.escape(text)   # short alias
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape as _esc
from typing import Union

# ── Типы ──────────────────────────────────────────────────────────────────

Numeric = Union[int, float, Decimal, str]

# ── Статус-эмодзи ─────────────────────────────────────────────────────────

STATUS_MAP: dict[str, str] = {
    # Успех
    "accepted":   "◾️",
    "approved":   "◾️",
    "paid":       "◾️",
    # Отказ
    "rejected":   "▫️",
    "cancelled":  "▫️",
    "blocked":    "✕",
    "not_a_scan": "✕",
    # Процесс
    "pending":    "⏳",
    "in_review":  "🔄",
}

_BOOL_ICONS = {True: "🟢", False: "🔴"}


# ── Форматтеры ────────────────────────────────────────────────────────────


def esc(text: str) -> str:
    """Короткий alias для html.escape."""
    return _esc(str(text))


def format_number(value: Numeric, *, decimals: int = 2) -> str:
    """Число с тысячными пробелами и фиксированными знаками после запятой.

    Без HTML-тегов — используй отдельно или в format_currency.

        format_number(10500)        → "10 500.00"
        format_number(1_000_000, 0) → "1 000 000"
    """
    try:
        f = float(value)
    except (ValueError, TypeError, InvalidOperation):
        return str(value)
    # Форматируем с нужным числом decimals, затем заменяем разделитель тысяч
    formatted = f"{f:,.{decimals}f}"      # "10,500.00"  (en locale)
    return formatted.replace(",", "\u2009")  # → "10 500.00"  (тонкий пробел)


def format_currency(
    value: Numeric,
    sign: str = "USDT",
    *,
    decimals: int = 2,
    before: bool = False,
) -> str:
    """Сумма в <code>...</code> с символом валюты.

        format_currency(10500)              → "<code>10 500.00</code> USDT"
        format_currency(10500, "₽")        → "<code>10 500.00</code> ₽"
        format_currency(10500, "$", before=True) → "<code>$ 10 500.00</code>"
    """
    num = format_number(value, decimals=decimals)
    if before:
        inner = f"{sign} {num}"
    else:
        inner = num
        suffix = f" {sign}"
    if before:
        return f"<code>{_esc(inner)}</code>"
    return f"<code>{_esc(inner)}</code>{suffix}"


def format_mono(text: str) -> str:
    """Wrap copyable data (IDs, wallets, eSIM numbers) in <code> tag.

    Пользователь может скопировать в один тап.

        format_mono("+79001234567")  → "<code>+79001234567</code>"
        format_mono("sim_42a9f")    → "<code>sim_42a9f</code>"
    """
    return f"<code>{_esc(str(text))}</code>"


# Alias — старое имя, используется в ui_builder.py
format_mono_copy = format_mono


def format_status(value: "bool | str") -> str:
    """Return the right icon for a boolean or named status.

        format_status(True)         → "🟢"
        format_status(False)        → "🔴"
        format_status("accepted")   → "◾️"
        format_status("pending")    → "⏳"
        format_status("unknown")    → "▪️"   (fallback)
    """
    if isinstance(value, bool):
        return _BOOL_ICONS[value]
    key = str(value).strip().lower()
    return STATUS_MAP.get(key, "▪️")


def format_count(value: Numeric, unit: str = "") -> str:
    """Число в <code>, опционально с единицей измерения.

        format_count(42)        → "<code>42</code>"
        format_count(42, "шт.") → "<code>42</code> шт."
    """
    try:
        n = int(float(value))
    except (ValueError, TypeError):
        n = value  # type: ignore[assignment]
    result = f"<code>{_esc(str(n))}</code>"
    if unit:
        result += f" {_esc(unit)}"
    return result


def format_bold(text: str) -> str:
    """<b>text</b> с экранированием."""
    return f"<b>{_esc(text)}</b>"


def format_italic(text: str) -> str:
    """<i>text</i> с экранированием."""
    return f"<i>{_esc(text)}</i>"


def format_user_link(username: str | None, telegram_id: int | str) -> str:
    """@username или <code>telegram_id</code> если username неизвестен.

        format_user_link("ivan", 123)  → "@ivan"
        format_user_link(None, 123)    → "<code>123</code>"
    """
    if username:
        return f"@{_esc(username)}"
    return format_mono(str(telegram_id))


def divider(char: str = "▰", length: int = 16) -> str:
    """Горизонтальный разделитель заданной длины и символа."""
    return char * length


def section(title: str, *, bullet: str = "◾️") -> str:
    """Заголовок секции с эмодзи-буллитом.

        section("Финансы")  → "◾️ <b>Финансы</b>"
    """
    return f"{bullet} <b>{_esc(title)}</b>"


# ── Rank system (turnover-based) ──────────────────────────────────────────

# (lower_bound_inclusive, upper_bound_exclusive_or_None, label)
RANK_TIERS: list[tuple[Decimal, Decimal | None, str]] = [
    (Decimal("0"),    Decimal("100"),   "[НАБЛЮДАТЕЛЬ]"),
    (Decimal("100"),  Decimal("1000"),  "[ПОЗНАЮЩИЙ]"),
    (Decimal("1000"), Decimal("5000"),  "[ПРОБУЖДЕННЫЙ]"),
    (Decimal("5000"), None,             "[ЭЛИТА СИНДИКАТА]"),
]


def get_rank_info(turnover: Numeric) -> tuple[str, Decimal | None]:
    """Return ``(rank_label, next_threshold)`` for the given all-time turnover.

    *next_threshold* is ``None`` for the top tier.

        get_rank_info(0)     → ("[НАБЛЮДАТЕЛЬ]",        Decimal("100"))
        get_rank_info(500)   → ("[ПОЗНАЮЩИЙ]",          Decimal("1000"))
        get_rank_info(9999)  → ("[ЭЛИТА СИНДИКАТА]", None)
    """
    try:
        value = Decimal(str(turnover))
    except (InvalidOperation, ValueError):
        value = Decimal("0")

    for lo, hi, label in RANK_TIERS:
        if hi is None or value < hi:
            return label, hi
    # Fallback: max tier
    return RANK_TIERS[-1][2], None


def rank_progress_bar(turnover: Numeric, *, cells: int = 10) -> str:
    """Block progress bar towards the next rank threshold (HTML-ready string).

        rank_progress_bar(50, 100)    ➔ "▰▰▰▰▰▱▱▱▱▱" (50 % до следующего ранга)
        rank_progress_bar(5000, 5000) ➔ "▰▰▰▰▰▰▰▰▰▰" (MAX TIER)
    """
    try:
        value = float(Decimal(str(turnover)))
    except (InvalidOperation, ValueError):
        value = 0.0

    _, next_threshold = get_rank_info(value)
    if next_threshold is None:
        return "▰" * cells

    # Determine the lower bound for this tier
    hi_d = float(next_threshold)
    base = 0.0
    for lo, hi, _ in RANK_TIERS:
        if hi is None or value < float(hi):
            base = float(lo)
            break

    span = max(hi_d - base, 1.0)
    ratio = min(max((value - base) / span, 0.0), 1.0)
    filled = int(round(ratio * cells))
    return ("▰" * filled) + ("▱" * (cells - filled))
