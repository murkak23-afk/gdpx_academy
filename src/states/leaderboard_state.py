from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class LeaderboardAdminState(StatesGroup):
    """FSM for /alead admin prize text editing."""

    waiting_for_prize_text = State()
