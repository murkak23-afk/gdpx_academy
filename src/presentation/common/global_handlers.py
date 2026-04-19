from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from src.core.utils.message_manager import MessageManager

router = Router(name="global_handlers")

@router.message(Command("cancel", "reset"))
@router.message(F.text.lower().in_({"отмена", "отменить", "cancel"}))
async def global_cancel_handler(message: Message, state: FSMContext, ui: MessageManager) -> None:
    """Глобальный перехватчик для сброса FSM стейта."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("В данный момент вы не находитесь ни в каком процессе.")
        return

    logger.info(f"User {message.from_user.id} cancelled state {current_state}")
    
    # Пытаемся очистить локальные буферы, если они есть
    from src.presentation.seller_portal.seller.submission import _media_buffer
    _media_buffer.pop(message.from_user.id, None)

    await state.clear()
    
    from src.presentation.seller_portal.seller.keyboards import get_seller_main_kb
    await ui.display(
        event=message, 
        text="🛑 <b>ТЕКУЩИЙ ПРОЦЕСС ОТМЕНЕН</b>\nВсе данные сброшены. Вы вернулись в главное меню.",
        reply_markup=await get_seller_main_kb()
    )
