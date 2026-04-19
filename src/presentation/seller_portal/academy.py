from __future__ import annotations

import logging

from aiogram import F, Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.base import PremiumBuilder
from src.presentation.lexicon.ru import Lex
from src.domain.users.user_service import UserService
from src.domain.users.academy_initiation import AcademyInitiation
from src.core.utils.media import media
from src.core.utils.ui_builder import GDPXRenderer
from src.core.utils.message_manager import MessageManager

router = Router(name="academy-initiation-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# --- Хендлеры принятия кодекса ---


@router.callback_query(F.data == "academy:start")
async def start_initiation(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Показ текста Кодекса Агента."""
    logger.info(f"User {callback.from_user.id} started academy initiation")
    await state.set_state(AcademyInitiation.accept_codex)

    kb = PremiumBuilder().primary(Lex.Academy.CODEX_ACCEPT_BUTTON, "academy:accept").as_markup()

    text = f"{Lex.Academy.CODEX_HEADER}\n\n{Lex.Academy.CODEX_TEXT}"
    banner = media.get("info.png")

    await ui.display(event=callback, text=text, reply_markup=kb, photo=banner)
    await callback.answer()


@router.callback_query(AcademyInitiation.accept_codex, F.data == "academy:accept")
async def accept_codex(callback: CallbackQuery, state: FSMContext, session: AsyncSession, ui: MessageManager, bot: Bot):
    """Завершение инициации после принятия кодекса с проверкой подписки."""
    from src.core.config import get_settings
    settings = get_settings()
    chat_id = settings.brand_chat_id or -1003716766270
    
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        if member.status in ["left", "kicked"]:
            return await callback.answer("✖ ОШИБКА: Сначала вступите в чат Синдиката!", show_alert=True)
    except Exception as e:
        logger.error(f"Academy subscription check error: {e}")
        return await callback.answer("⚠️ Ошибка проверки подписки. Попробуйте позже.", show_alert=True)

    logger.info(f"User {callback.from_user.id} accepted codex")

    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(callback.from_user.id)
    user.has_accepted_codex = True
    await session.commit()

    await state.clear()
    await callback.answer("Кодекс принят. Добро пожаловать!", show_alert=True)

    from src.presentation.seller_portal.registration import _show_main_dashboard

    await _show_main_dashboard(callback, user, session, ui)
