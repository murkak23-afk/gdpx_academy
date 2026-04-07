from aiogram.fsm.state import State, StatesGroup

class AcademyInitiation(StatesGroup):
    accept_codex = State()
    set_pin = State()
    confirm_pin = State()
