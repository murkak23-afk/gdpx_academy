"""Текст «домашнего» экрана админ-панели (одна точка правды для reply + inline)."""

from __future__ import annotations

from src.keyboards.constants import COMMAND_ADM_OPER

ADMIN_PANEL_HOME_TEXT = (
    "Админ-панель.\n\n"
    "Команды:\n"
    f"• {COMMAND_ADM_OPER} — категории (подтипы операторов)\n"
    "• /admin — это меню\n\n"
    "Выход — кнопка «Выйти из админ панели».\n"
    "Используйте кнопки меню внизу."
)
