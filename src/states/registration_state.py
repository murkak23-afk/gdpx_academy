from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    """Состояния быстрой регистрации пользователя."""

    waiting_for_language = State()
