from aiogram.fsm.state import State, StatesGroup


class QRDeliveryStates(StatesGroup):
    """FSM-состояния для процесса выдачи QR-кодов."""
    waiting_for_count = State()
