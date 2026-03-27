"""Агрегация подтипов категорий (названий в БД) в «основные операторы» для статистики eSIM.

Категории в админке задаются свободным текстом (`Category.title`). Этот модуль
сопоставляет заголовок категории с одной из фиксированных групп для отчётов
«по основным операторам». Всё, что не распознано, попадает в корзину «Другое»
(см. `SubmissionService.get_user_esim_seller_stats`).
"""

from __future__ import annotations

# Кортежи (отображаемое имя, ключевые подстроки в нижнем регистре).
# Порядок важен: берётся первое совпадение по вхождению подстроки в название.
MAIN_OPERATOR_GROUPS: list[tuple[str, frozenset[str]]] = [
    (
        "МТС",
        frozenset({"мтс", "mts"}),
    ),
    (
        "Билайн",
        frozenset({"билайн", "beeline", "вымпелком", "vimpelcom"}),
    ),
    (
        "МегаФон",
        frozenset({"мегафон", "megafon"}),
    ),
    (
        "Теле2",
        frozenset({"теле2", "tele2", "теле 2", "tele 2"}),
    ),
    (
        "Йота",
        frozenset({"йота", "yota"}),
    ),
]


def category_title_to_main_group_label(title: str) -> str | None:
    """Возвращает метку основной группы для заголовка категории или None для «Другое».

    Сопоставление по подстрокам без учёта регистра. Если подходит несколько групп,
    используется первая из `MAIN_OPERATOR_GROUPS`.
    """

    normalized = title.strip().lower()
    for label, keywords in MAIN_OPERATOR_GROUPS:
        for kw in keywords:
            if kw in normalized:
                return label
    return None
