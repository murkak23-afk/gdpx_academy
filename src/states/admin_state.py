from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminRequestsState(StatesGroup):
    """Ввод строки «telegram_id лимит» для ежедневного запроса на выгрузку."""

    waiting_for_quota_line = State()
    waiting_for_delete_line = State()


class AdminCategoryState(StatesGroup):
    """Редактирование категорий (подтипов операторов) через бота."""

    waiting_for_add_title = State()
    waiting_for_add_payout_rate = State()
    waiting_for_add_total_limit = State()
    waiting_for_add_description = State()
    waiting_for_add_photo = State()
    waiting_for_pick_category = State()
    waiting_for_edit_value = State()


class AdminBroadcastState(StatesGroup):
    """Состояние ввода текста для массовой рассылки."""

    waiting_for_text = State()
