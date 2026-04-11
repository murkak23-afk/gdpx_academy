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
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="admin-domain-router")
_renderer = GDPXRenderer()

from src.filters.admin import IsAdminFilter, IsOwnerFilter
from src.keyboards.owner import get_owner_main_kb
from src.handlers.admin.owner_cabinet import router as owner_cabinet_router

# --- МОДЕРАТОР (Команда /a или /admin) ---

async def on_enter_moderator_panel(event: Message | CallbackQuery, session: AsyncSession, state: FSMContext | None = None) -> None:
    """Центральный вход в панель модератора."""
    if state:
        await state.clear()
        
    from src.handlers.moderation.entry import _render_dashboard_text
    from src.keyboards.moderation import get_mod_dashboard_kb
    
    text, stats = await _render_dashboard_text(session, event.from_user.id)
    kb = get_mod_dashboard_kb(stats)
    
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")

@router.message(Command("a", "admin", prefix="/!"))
@router.message(F.text.casefold().regexp(r"^[/!](a|admin)$"))
@router.message(F.text.casefold().contains("модерация"))
async def cmd_moderator_panel(message: Message, session: AsyncSession, state: FSMContext) -> None:
    from src.services.admin_service import AdminService
    admin_svc = AdminService(session=session)
    if not await admin_svc.is_admin_strictly(message.from_user.id):
        return
    await on_enter_moderator_panel(message, session, state)


# --- ВЛАДЕЛЕЦ (Команда /o или /owner) ---

async def on_enter_owner_panel(event: Message | CallbackQuery, session: AsyncSession, state: FSMContext | None = None) -> None:
    """Центральный вход в панель владельца."""
    if state:
        await state.clear()
        
    from src.services.admin_stats_service import AdminStatsService
    stats_svc = AdminStatsService(session)
    stats = await stats_svc.get_owner_summary_stats()
    
    # Дополнительно считаем % зачета за 24ч для дашборда
    from datetime import datetime, timezone, timedelta
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    platform_stats = await stats_svc.get_platform_stats(start, datetime.now(timezone.utc))
    stats["accept_rate"] = platform_stats["reject_rate"] # В платформе это reject_rate, инвертируем или используем как есть
    
    stats["username"] = event.from_user.username or str(event.from_user.id)
    text = _renderer.render_owner_dashboard(stats)
    
    kb = get_owner_main_kb()
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")

@router.message(Command("o", "owner"), IsOwnerFilter())
async def cmd_owner_panel(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await on_enter_owner_panel(message, session, state)

@router.callback_query(F.data == "admin_moderation")
async def cb_admin_moderation_redirect(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Редирект старого колбэка на новый формат."""
    await on_enter_moderator_panel(callback, session, state)
    await callback.answer()


from src.keyboards.factory import NavCD
@router.callback_query(NavCD.filter(F.to == "admin_menu"))
async def back_to_admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    from src.services.admin_service import AdminService
    admin_svc = AdminService(session=session)
    
    # Если это владелец, по умолчанию возвращаем в его кабинет
    if await admin_svc.is_owner_strictly(callback.from_user.id):
        await on_enter_owner_panel(callback, session, state)
    # Если это админ, возвращаем в панель модератора
    elif await admin_svc.is_admin_strictly(callback.from_user.id):
        await on_enter_moderator_panel(callback, session, state)
    else:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
    await callback.answer()


router.include_router(owner_cabinet_router)

__all__ = ["router", "on_enter_moderator_panel", "on_enter_owner_panel"]
