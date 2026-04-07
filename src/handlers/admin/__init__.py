from __future__ import annotations

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
from src.keyboards.builders import get_admin_main_kb
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="admin-domain-router")
_renderer = GDPXRenderer()

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
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = event.from_user.username or str(event.from_user.id)
    text = _renderer.render_admin_dashboard(stats)
    
    if isinstance(event, Message):
        await event.answer(text, reply_markup=get_admin_main_kb(), parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=get_admin_main_kb(), parse_mode="HTML")

@router.message(Command("a"))
@router.message(F.text == "⚖️ Модерация") # Можно и так зайти, если нужно
async def cmd_admin_panel(message: Message, session: AsyncSession) -> None:
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    await on_enter_admin_panel(message, session)

from src.keyboards.factory import NavCD
@router.callback_query(NavCD.filter(F.to == "admin_menu"))
async def back_to_admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await on_enter_admin_panel(callback, session)
    await callback.answer()

__all__ = ["router", "on_enter_admin_panel"]
