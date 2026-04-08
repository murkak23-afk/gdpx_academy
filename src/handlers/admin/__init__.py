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
from src.keyboards import get_admin_main_kb
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

from src.filters.admin import IsAdminFilter, IsOwnerFilter
from src.keyboards.owner import get_moderator_main_kb, get_owner_main_kb
from src.handlers.admin.owner_cabinet import router as owner_cabinet_router

# --- МОДЕРАТОР (Команда /a или /admin) ---

async def on_enter_moderator_panel(event: Message | CallbackQuery, session: AsyncSession) -> None:
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = event.from_user.username or str(event.from_user.id)
    text = _renderer.render_admin_dashboard(stats)
    
    kb = get_moderator_main_kb()
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")

@router.message(Command("a", "admin"), IsAdminFilter())
@router.message(F.text.casefold().contains("модерация"))
async def cmd_moderator_panel(message: Message, session: AsyncSession) -> None:
    from src.services.admin_service import AdminService
    if not await AdminService(session=session).is_admin_strictly(message.from_user.id):
        return
    await on_enter_moderator_panel(message, session)


# --- ВЛАДЕЛЕЦ (Команда /o или /owner) ---

async def on_enter_owner_panel(event: Message | CallbackQuery, session: AsyncSession) -> None:
    from src.services.admin_stats_service import AdminStatsService
    stats_svc = AdminStatsService(session)
    stats = await stats_svc.get_owner_summary_stats()
    
    stats["username"] = event.from_user.username or str(event.from_user.id)
    text = _renderer.render_owner_dashboard(stats)
    
    kb = get_owner_main_kb()
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")

@router.message(Command("o", "owner"), IsOwnerFilter())
async def cmd_owner_panel(message: Message, session: AsyncSession) -> None:
    await on_enter_owner_panel(message, session)

@router.callback_query(F.data == "admin_moderation")
async def cb_admin_moderation_redirect(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Редирект старого колбэка на новый формат."""
    from src.handlers.moderation.entry import cmd_moderation_dashboard_cb
    # Вызываем напрямую логику дашборда
    from src.handlers.moderation.entry import _render_dashboard_text
    from src.keyboards.moderation import get_mod_dashboard_kb
    text, pending, in_work = await _render_dashboard_text(session, callback.from_user.id)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_mod_dashboard_kb(pending, in_work), parse_mode="HTML")
    await callback.answer()


from src.keyboards.factory import NavCD
@router.callback_query(NavCD.filter(F.to == "admin_menu"))
async def back_to_admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    # Определяем, куда возвращать пользователя
    admin_svc = AdminService(session=session)
    if await admin_svc.is_owner_strictly(callback.from_user.id):
        await on_enter_owner_panel(callback, session)
    elif await admin_svc.is_admin_strictly(callback.from_user.id):
        await on_enter_moderator_panel(callback, session)
    else:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
    await callback.answer()

router.include_router(owner_cabinet_router)

__all__ = ["router", "on_enter_moderator_panel", "on_enter_owner_panel"]
