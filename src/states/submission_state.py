from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SubmissionState(StatesGroup):
    """Состояния создания новой симки контента."""

    waiting_for_category = State()
    waiting_for_photo = State()
    waiting_for_description = State()
    waiting_for_batch_delete_phone = State()
    waiting_for_batch_csv_choice = State()
    waiting_for_material_edit_description = State()
    waiting_for_material_edit_media = State()
