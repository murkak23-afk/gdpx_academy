from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CatConstructorState(StatesGroup):
    """Пошаговый конструктор категории: Оператор → Тип → Холд → Цена."""

    step_operator = State()
    step_type = State()
    step_hold = State()
    step_price = State()
    step_confirm = State()
    edit_price = State()


class AdminBroadcastState(StatesGroup):
    """Состояние ввода текста для массовой рассылки."""

    waiting_for_text = State()


class AdminSearchSimState(StatesGroup):
    """Поиск симки по последним цифрам номера."""

    waiting_for_digits = State()


class AdminGradeOtherState(StatesGroup):
    """Ввод произвольной причины отказа (Брак: Другое)."""

    waiting_for_reason = State()


class AdminPayoutState(StatesGroup):
    """Двухэтапное подтверждение выплаты."""

    waiting_for_payout_confirm = State()
    waiting_for_topup_amount = State()
