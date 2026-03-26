"""Основные операторы eSIM: группы для статистики по названию категории.

Верхний уровень — бренды (Билайн, МТС, Т2 и др.); подтипы задаются отдельными
строками категорий (например «МТС(Салон)», «МТС(Корп)», «Билайн(ГК)»). Каждая
такая строка — отдельный выбор при продаже и отдельный дневной лимит в «Запросах».
"""

from __future__ import annotations

# (подпись в статистике, подстроки для сопоставления с Category.title)
MAIN_OPERATOR_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Билайн / Билайн-Корп", ("билайн", "beeline")),
    ("МТС / МТС-Корп", ("мтс", "mts")),
    ("Т2 / Т2-Корп", ("т2", "т-2", "tele2", "теле2")),
    ("Йота", ("йота", "yota")),
    ("МегаФон", ("мегафон", "megafon")),
    ("Сбер", ("сбер", "sber")),
    ("ГазПром", ("газпром", "gazprom")),
    ("ВТБ", ("втб", "vtb")),
]


def category_title_to_main_group_label(title: str) -> str | None:
    """Возвращает метку основной группы или None, если не совпало."""

    t = title.lower().strip()
    for label, patterns in MAIN_OPERATOR_GROUPS:
        if any(p in t for p in patterns):
            return label
    return None


def main_group_labels_ordered() -> list[str]:
    return [label for label, _ in MAIN_OPERATOR_GROUPS]
