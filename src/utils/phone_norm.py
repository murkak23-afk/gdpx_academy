"""Нормализация номера для дублей и маска для публичных подписей."""

from __future__ import annotations
import re

def normalize_phone_key(text: str | None) -> str | None:
    """Ключ для поиска дублей: только цифры, RU 8→7, 10 цифр → с ведущей 7."""
    d = "".join(c for c in (text or "") if c.isdigit())
    if not d:
        return None
    if d.startswith("8") and len(d) == 11:
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d

def normalize_phone_strict(text: str | None) -> str | None:
    """Строгий формат для БД: 79XXXXXXXXX (11 цифр, без +)."""
    key = normalize_phone_key(text)
    if key is None or len(key) != 11 or not key.startswith("79"):
        return None
    return key

PHONE_NORM_ERROR_HTML = (
    "❌ <b>Неверный формат номера</b>\n\n"
    "Введите российский мобильный номер.\n"
    "Допустимые форматы:\n"
    "<code>+79001112233</code>\n"
    "<code>89001112233</code>\n"
    "<code>9001112233</code>\n\n"
    "Бот автоматически приведёт к формату <code>79XXXXXXXXX</code>."
)

def mask_phone_public(phone: str | None) -> str:
    """Формат для рабочих чатов: +7967… — без полного номера."""
    p = (phone or "").strip()
    if not p:
        return "—"
    if len(p) <= 6:
        return f"{p}…"
    # Показываем начало (код/префикс) и многоточие; без «хвоста» — как в ТЗ.
    return f"{p[:5]}…"

def extract_and_normalize_phone(text: str | None) -> str | None:
    """
    Умный поиск первого мобильного номера РФ в тексте (среди мусора).
    Поддерживает форматы: +79xx, 8 (9xx), 9xx-xx-xx и любые опечатки.
    Возвращает строгий формат БД: 79XXXXXXXXX (11 цифр).
    """
    if not text:
        return None

    # Ищем: границы не-цифр, опциональный код (+7/7/8), скобки/пробелы/дефисы
    # и строго 10 цифр мобильного номера, начинающегося с 9.
    pattern = r"(?:^|[^\d])(?:\+?7|8)?[\s\-\(\)]*([9]\d{2})[\s\-\(\)]*(\d{3})[\s\-\(\)]*(\d{2})[\s\-\(\)]*(\d{2})(?:[^\d]|$)"
    match = re.search(pattern, text)

    if match:
        # Собираем все 4 группы: 9XX, XXX, XX, XX с приставкой 7
        return f"7{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}"

    return None