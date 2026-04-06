from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer
from src.keyboards.builders import get_seller_main_kb
from src.keyboards.factory import NavCD
from src.database.models.enums import UserLanguage

router = Router(name="start-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

async def _show_main_dashboard(target: Message | CallbackQuery, user, session: AsyncSession):
    """Вспомогательная функция для отрисовки красивого дашборда."""
    dashboard_stats = await SubmissionService(session=session).get_user_dashboard_stats(user.id)
    
    # Формируем данные для рендерера (render_dashboard)
    render_data = {
        "username": user.username or "resident",
        "telegram_id": user.telegram_id,
        "approved_count": int(dashboard_stats.get("accepted", 0)),
        "pending_count": int(dashboard_stats.get("pending", 0)),
        "in_review_count": 0, # В агрегате dashboard_stats они уже в pending
        "rejected_count": int(dashboard_stats.get("rejected", 0)),
        "total_payout_amount": float(user.total_paid or 0),
    }
    
    text = _renderer.render_dashboard(render_data)
    banner = media.get("items.jpg")
    
    if isinstance(target, Message):
        await target.answer_photo(
            photo=banner,
            caption=text,
            reply_markup=get_seller_main_kb(),
            parse_mode="HTML"
        )
    else:
        try:
            await target.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text),
                reply_markup=get_seller_main_kb()
            )
        except Exception:
            await target.message.answer_photo(photo=banner, caption=text, reply_markup=get_seller_main_kb())
            await target.message.delete()

@router.message(CommandStart(), StateFilter(None))
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Точка входа: регистрация и красивый дашборд."""
    await state.clear()
    
    user = await UserService(session=session).register_seller(
        tg_user=message.from_user,
        language=UserLanguage.RU,
    )
    await session.flush()
    await _show_main_dashboard(message, user, session)

@router.callback_query(NavCD.filter(F.to == "menu"))
async def back_to_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Возврат в меню через колбэк."""
    await state.clear()
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    await _show_main_dashboard(callback, user, session)
    await callback.answer()
