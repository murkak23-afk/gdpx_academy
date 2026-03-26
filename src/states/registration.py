from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    """Состояния быстрой регистрации пользователя."""

    waiting_for_language = State()


class SubmissionState(StatesGroup):
    """Состояния создания новой карточки контента."""

    waiting_for_category = State()
    waiting_for_photo = State()
    waiting_for_description = State()


class AdminModerationForwardState(StatesGroup):
    """Выбор чата или пользователя (ЛС) для пересылки из очереди модерации."""

    waiting_for_target = State()


class AdminRequestsState(StatesGroup):
    """Ввод строки «telegram_id лимит» для ежедневного запроса на выгрузку."""

    waiting_for_quota_line = State()
    waiting_for_search_query = State()


class AdminCategoryState(StatesGroup):
    """Редактирование категорий (подтипов операторов) через бота."""

    # Добавление
    waiting_for_add_title = State()
    waiting_for_add_payout_rate = State()
    waiting_for_add_total_limit = State()
    waiting_for_add_description = State()
    waiting_for_add_photo = State()

    # Редактирование
    waiting_for_edit_id = State()
    waiting_for_edit_value = State()


class AdminBroadcastState(StatesGroup):
    """Состояние ввода текста для массовой рассылки."""

    waiting_for_text = State()


class AdminBatchPickState(StatesGroup):
    """Выбор части pending-карточек продавца перед пересылкой в чат."""

    waiting_for_submission_ids = State()
