from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminModerationForwardState(StatesGroup):
    """Выбор чата или пользователя (ЛС) для пересылки из очереди модерации."""

    waiting_for_target = State()
    waiting_for_confirm = State()
    waiting_for_hold_selection = State()


class AdminBatchPickState(StatesGroup):
    """Выбор части pending-карточек продавца перед пересылкой в чат."""

    waiting_for_submission_ids = State()
    waiting_for_action = State()


class AdminInReviewLookupState(StatesGroup):
    """Поиск симок в «В работе»: активные и архив."""

    waiting_for_query = State()

class AdminInworkBatchState(StatesGroup):
    """Пакетный выбор карточек в «В работe»."""

    selecting = State()


class AdminCardFilterState(StatesGroup):
    """Поиск внутри карточек продавца для in_review и буфера."""

    waiting_for_inwork_query = State()
    waiting_for_buffer_query = State()


class AdminBufferAdjustState(StatesGroup):
    """Ручная корректировка карточек в буфере."""

    waiting_for_category_id = State()