from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.admin_service import AdminService
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus
from src.utils.ui_builder import GDPXRenderer
from src.keyboards.factory import AdminMenuCD, NavCD
from src.keyboards.builders import get_admin_main_kb
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="admin-menu-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# Константы для совместимости
PHONE_QUERY_PATTERN = r"^[+\d][\d \-()]{6,24}$"

async def _render_admin_moderation_card(submission: Submission, session: AsyncSession) -> str:
    """Публичный метод для отрисовки карточки в старых разделах."""
    from src.utils.submission_format import moderation_admin_card_html
    from src.database.models.user import User
    from src.database.models.category import Category
    
    seller = await session.get(User, submission.user_id)
    category = await session.get(Category, submission.category_id)
    
    seller_label = f"@{seller.username}" if seller and seller.username else f"ID:{submission.user_id}"
    cat_title = category.title if category else "Без категории"
    
    return moderation_admin_card_html(
        submission=submission,
        seller_label=seller_label,
        category_title=cat_title
    )

async def _fetch_admin_board_stats(session: AsyncSession) -> dict:
    pending = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING))
    in_review = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW))
    accepted = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.ACCEPTED))
    rejected = await session.scalar(select(func.count(Submission.id)).where(Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN])))
    
    return {
        "pending_count": pending or 0,
        "in_review_count": in_review or 0,
        "approved_count": accepted or 0,
        "rejected_count": rejected or 0,
    }

async def on_enter_admin_panel(event: Message | CallbackQuery, session: AsyncSession) -> None:
    if isinstance(event, Message):
        await cmd_admin_panel(event, session)
    else:
        stats = await _fetch_admin_board_stats(session)
        stats["username"] = event.from_user.username or str(event.from_user.id)
        text = _renderer.render_admin_dashboard(stats)
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=get_admin_main_kb(), parse_mode="HTML")

@router.message(Command("a"))
async def cmd_admin_panel(message: Message, session: AsyncSession) -> None:
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = message.from_user.username or str(message.from_user.id)
    text = _renderer.render_admin_dashboard(stats)
    await message.answer(text, reply_markup=get_admin_main_kb(), parse_mode="HTML")

@router.callback_query(NavCD.filter(F.to == "admin_menu"))
async def back_to_admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await on_enter_admin_panel(callback, session)
    await callback.answer()

@router.callback_query(AdminMenuCD.filter(F.section == "search"))
async def admin_search_start(callback: CallbackQuery) -> None:
    await callback.answer("Функция поиска SIM активна. Перейдите в раздел Модерация.", show_alert=True)

@router.callback_query(AdminMenuCD.filter(F.section == "stats"))
async def admin_stats_menu(callback: CallbackQuery) -> None:
    await callback.answer("Раздел аналитики в разработке", show_alert=True)

@router.callback_query(AdminMenuCD.filter(F.section == "broadcast"))
async def admin_broadcast_start(callback: CallbackQuery) -> None:
    await callback.answer("Рассылка: используйте команду /broadcast", show_alert=True)
