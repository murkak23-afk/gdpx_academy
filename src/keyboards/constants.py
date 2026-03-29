"""Общие подписи и callback_data для навигации «назад»."""

from __future__ import annotations

import unicodedata

from src.keyboards.callbacks import CB_NAV_INLINE_BACK

# Reply-кнопка (одинаковая для селлера и админа)
REPLY_BTN_BACK = "⬅️ Назад"

# Кнопки входа/выхода из админ-панели (не входят в ADMIN_MAIN_MENU_TEXTS)
BUTTON_ENTER_ADMIN_PANEL = "Войти в админ панель"
BUTTON_EXIT_ADMIN_PANEL = "Выйти из админ панели"

# Тексты главного reply-меню chief admin (должны совпадать с admin_main_menu_keyboard)
ADMIN_MAIN_MENU_TEXTS = frozenset(
    {
        "Очередь",
        "В работе",
        "🏃 В работе",
        "Выплаты",
        "Рассылка",
        "Архив (7days)",
    }
)

# Убрать inline-клавиатуру и вернуть фокус на reply-меню админа
CALLBACK_INLINE_BACK = CB_NAV_INLINE_BACK



def normalize_reply_menu_text(text: str | None) -> str | None:
    """NFC + strip + casefold: одинаковые кнопки с разным регистром/пробелами совпадают."""

    if text is None:
        return None
    return unicodedata.normalize("NFC", text.strip()).casefold()


def match_admin_menu_canonical(text: str | None) -> str | None:
    """Возвращает канонический текст кнопки админ-меню или None."""

    n = normalize_reply_menu_text(text)
    if n is None:
        return None
    return _ADMIN_MENU_NORM_TO_CANON.get(n)


def is_admin_main_menu_text(text: str | None) -> bool:
    return match_admin_menu_canonical(text) is not None


def _build_admin_norm_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for label in ADMIN_MAIN_MENU_TEXTS:
        key = normalize_reply_menu_text(label)
        if key is not None:
            m[key] = label
    return m


_ADMIN_MENU_NORM_TO_CANON = _build_admin_norm_map()


def _build_sell_esim_norm_aliases() -> frozenset[str]:
    """Латиница eSIM и частая опечатка кириллицей «есим»; разный регистр."""

    variants = (
        "Продать eSIM",
        "Продать есим",
        "Продать Есим",
        "продать eSIM",
        "продать есим",
    )
    out: set[str] = set()
    for v in variants:
        nv = normalize_reply_menu_text(v)
        if nv is not None:
            out.add(nv)
    return frozenset(out)


SELL_ESIM_NORM_ALIASES = _build_sell_esim_norm_aliases()


def is_sell_esim_button(text: str | None) -> bool:
    n = normalize_reply_menu_text(text)
    return n is not None and n in SELL_ESIM_NORM_ALIASES
