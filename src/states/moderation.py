from __future__ import annotations
from aiogram.fsm.state import State, StatesGroup

class ModerationStates(StatesGroup):
    """Премиум-состояния для цикла дефектовки."""
    main_dashboard = State()
    conveyor_active = State()
    waiting_for_rejection_reason = State()
    waiting_for_custom_comment = State()  # Ожидание ввода причины руками
    waiting_for_topup_amount = State()  # Ожидание ввода суммы пополнения вручную
    search_query = State()
    batch_processing = State()
    batch_processing = State()
    batch_reason_select = State()
    batch_status_select = State()
    batch_custom_comment = State()  