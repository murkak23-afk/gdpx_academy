from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

router = Router(name="global-fsm-fallback")

@router.message(F.state, content_types=types.ContentType.ANY)
async def fsm_fallback_handler(message: types.Message, state: FSMContext):
    if message.text in ("/start", "/cancel"):
        await state.clear()
        await message.answer("Сценарий сброшен.")
        return
    await message.answer(
        "⚠️ Неподдерживаемый формат. Пожалуйста, отправьте корректный тип данных или нажмите 'Отмена'."
    )
