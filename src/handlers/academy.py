from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.base import PremiumBuilder
from src.lexicon.ru import Lex
from src.services.user_service import UserService
from src.states.academy_initiation import AcademyInitiation
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer

router = Router(name="academy-initiation-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# --- Хендлеры принятия кодекса ---


@router.callback_query(F.data == "academy:start")
async def start_initiation(callback: CallbackQuery, state: FSMContext):
    """Показ текста Кодекса Агента."""
    logger.info(f"User {callback.from_user.id} started academy initiation")
    await state.set_state(AcademyInitiation.accept_codex)

    kb = PremiumBuilder().primary(Lex.Academy.CODEX_ACCEPT_BUTTON, "academy:accept").as_markup()

    text = f"{Lex.Academy.CODEX_HEADER}\n\n{Lex.Academy.CODEX_TEXT}"
    banner = media.get("academy.jpg")

    try:
        logger.info(f"Attempting to edit media for user {callback.from_user.id} with academy.jpg")
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Error editing media in start_initiation: {e}")
        try:
            await callback.message.answer_photo(photo=banner, caption=text, reply_markup=kb, parse_mode="HTML")
            await callback.message.delete()
        except Exception:
            from src.utils.text_format import edit_message_text_or_caption_safe
            await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb)
        try:
            await callback.message.delete()
        except Exception:
            pass

    await callback.answer()


@router.callback_query(AcademyInitiation.accept_codex, F.data == "academy:accept")
async def accept_codex(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Завершение инициации после принятия кодекса."""
    logger.info(f"User {callback.from_user.id} accepted codex")

    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(callback.from_user.id)
    user.has_accepted_codex = True
    await session.commit()

    await state.clear()
    await callback.answer("Кодекс принят. Добро пожаловать!", show_alert=True)

    from src.handlers.registration import _show_main_dashboard

    await _show_main_dashboard(callback, user, session)
