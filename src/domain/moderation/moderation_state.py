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


class ModerationStates(StatesGroup):
    """Премиум-состояния для цикла дефектовки."""

    main_dashboard = State()
    conveyor_active = State()
    waiting_for_rejection_reason = State()
    waiting_for_custom_comment = State()  # Ожидание ввода причины руками
    waiting_for_topup_amount = State()  # Ожидание ввода суммы пополнения вручную
    search_query = State()
    batch_processing = State()
    batch_reason_select = State()
    batch_status_select = State()
    batch_custom_comment = State()
