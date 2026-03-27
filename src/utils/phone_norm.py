"""Нормализация номера для дублей и маска для публичных подписей."""

from __future__ import annotations


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
    """Строгий формат для БД: +7XXXXXXXXXX."""

    key = normalize_phone_key(text)
    if key is None or len(key) != 11 or not key.startswith("7"):
        return None
    return f"+{key}"


def mask_phone_public(phone: str | None) -> str:
    """Формат для рабочих чатов: +7967… — без полного номера."""

    p = (phone or "").strip()
    if not p:
        return "—"
    if len(p) <= 6:
        return f"{p}…"
    # Показываем начало (код/префикс) и многоточие; без «хвоста» — как в ТЗ.
    return f"{p[:5]}…"
