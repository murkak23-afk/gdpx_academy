from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SubmissionState(StatesGroup):
    """Премиум-состояния загрузки eSIM."""
    waiting_for_category = State()
    waiting_for_media = State()