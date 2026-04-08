from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer
from src.keyboards import get_pin_pad_kb
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import PinPadCD
from src.lexicon.ru import Lex
from src.states.academy_initiation import AcademyInitiation

router = Router(name="academy-initiation-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# --- Хендлеры принятия кодекса ---

@router.callback_query(F.data == "academy:start")
async def start_initiation(callback: CallbackQuery, state: FSMContext):
    """Показ текста Кодекса Агента."""
    logger.info(f"User {callback.from_user.id} started academy initiation")
    await state.set_state(AcademyInitiation.accept_codex)
    
    kb = (PremiumBuilder()
          .primary(Lex.Academy.CODEX_ACCEPT_BUTTON, "academy:accept")
          .as_markup())
    
    text = f"{Lex.Academy.CODEX_HEADER}\n\n{Lex.Academy.CODEX_TEXT}"
    banner = media.get("academy.jpg")
    
    try:
        logger.info(f"Attempting to edit media for user {callback.from_user.id} with academy.jpg")
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Error editing media in start_initiation: {e}")
        await callback.message.answer_photo(photo=banner, caption=text, reply_markup=kb, parse_mode="HTML")
        try:
            await callback.message.delete()
        except Exception:
            pass
    
    await callback.answer()

@router.callback_query(AcademyInitiation.accept_codex, F.data == "academy:accept")
async def accept_codex(callback: CallbackQuery, state: FSMContext):
    """Переход к установке PIN после принятия кодекса."""
    logger.info(f"User {callback.from_user.id} accepted codex")
    await state.set_state(AcademyInitiation.set_pin)
    await state.update_data(pin_input="")
    
    kb = get_pin_pad_kb("", context="init")
    await callback.message.edit_caption(
        caption=Lex.Academy.PIN_PROMPT,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer("Кодекс принят. Установите PIN.")

# --- Хендлеры PIN-пада ---

@router.callback_query(PinPadCD.filter())
async def process_pin_pad(callback: CallbackQuery, callback_data: PinPadCD, state: FSMContext, session: AsyncSession):
    """Обработка нажатий на кнопки PIN-пада."""
    action = callback_data.action
    current_state = await state.get_state()
    
    if current_state not in [AcademyInitiation.set_pin, AcademyInitiation.confirm_pin]:
        return # Не наше состояние
        
    state_data = await state.get_data()
    current_pin = state_data.get("pin_input", "")
    
    if action == "digit":
        digit = callback_data.value
        if len(current_pin) < 6:
            current_pin += digit
            await state.update_data(pin_input=current_pin)
    
    elif action == "backspace":
        current_pin = current_pin[:-1]
        await state.update_data(pin_input=current_pin)
        
    elif action == "cancel":
        logger.info(f"User {callback.from_user.id} cancelled PIN setup")
        await state.clear()
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        from src.handlers.registration import _show_main_dashboard
        await _show_main_dashboard(callback, user, session)
        return

    elif action == "confirm":
        if len(current_pin) < 4:
            await callback.answer("PIN должен быть от 4 до 6 цифр!", show_alert=True)
            return
            
        if current_state == AcademyInitiation.set_pin:
            await state.update_data(first_pin=current_pin, pin_input="")
            await state.set_state(AcademyInitiation.confirm_pin)
            await callback.message.edit_caption(
                caption=Lex.Academy.PIN_CONFIRM_PROMPT,
                reply_markup=get_pin_pad_kb("", context="init"),
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        else: # confirm_pin
            first_pin = state_data.get("first_pin")
            if current_pin != first_pin:
                # Уведомление об ошибке с поддержкой HTML (через сообщение, так как alert не умеет в HTML)
                await callback.answer() 
                await callback.message.answer(Lex.Academy.PIN_MISMATCH, parse_mode="HTML")
                
                await state.update_data(pin_input="")
                await callback.message.edit_caption(
                    caption=f"✖ {Lex.Academy.PIN_MISMATCH}\n\n{Lex.Academy.PIN_CONFIRM_PROMPT}",
                    reply_markup=get_pin_pad_kb("", context="init"),
                    parse_mode="HTML"
                )
                return
            
            # PIN совпал! Сохраняем данные
            logger.info(f"User {callback.from_user.id} successfully set PIN")
            user_service = UserService(session=session)
            user = await user_service.get_by_telegram_id(callback.from_user.id)
            user.has_accepted_codex = True
            user.pin_code = current_pin
            user.is_pin_enabled = True
            await session.flush()
            
            await state.clear()
            # Уведомление об успехе с поддержкой HTML
            await callback.answer()
            await callback.message.answer(Lex.Academy.PIN_SUCCESS, parse_mode="HTML")
            
            from src.handlers.registration import _show_main_dashboard
            await _show_main_dashboard(callback, user, session)
            return

    # Обновляем клавиатуру с маскированным вводом
    masked_pin = "●" * len(current_pin)
    prompt = Lex.Academy.PIN_PROMPT if current_state == AcademyInitiation.set_pin else Lex.Academy.PIN_CONFIRM_PROMPT
    
    try:
        await callback.message.edit_caption(
            caption=f"{prompt}\n\nВвод: <code>{masked_pin}</code>",
            reply_markup=get_pin_pad_kb(current_pin, context="init"),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()
