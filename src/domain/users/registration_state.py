from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    """Состояния быстрой регистрации пользователя."""

    waiting_for_language = State()
    waiting_for_pseudonym = State()
    waiting_for_faq = State()
    waiting_for_codex = State()
