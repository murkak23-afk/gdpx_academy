from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.domain.moderation.admin_service import AdminService
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import GDPXRenderer
from src.core.logger import logger

router = Router(name="admin-domain-router")
_renderer = GDPXRenderer()

from src.presentation.filters.admin import IsAdminFilter, IsOwnerFilter
from src.presentation.admin_panel.admin.owner_cabinet import router as owner_cabinet_router
from src.presentation.admin_panel.owner import get_owner_main_kb

# --- МОДЕРАТОР (Команда /a или /admin) ---

async def on_enter_moderator_panel(event: Message | CallbackQuery, session: AsyncSession, ui: MessageManager, state: FSMContext | None = None) -> None:
    """Центральный вход в панель модератора."""
    if state:
        await state.clear()
        
    from src.presentation.admin_panel.moderation.entry import _render_dashboard_text
    from src.presentation.admin_panel.moderation import get_mod_dashboard_kb
    
    text, stats = await _render_dashboard_text(session, event.from_user.id)
    kb = get_mod_dashboard_kb(stats)
    
    await ui.display(event=event, text=text, reply_markup=kb)

@router.message(Command("a", "admin", prefix="/!"))
@router.message(F.text.casefold().regexp(r"^[/!](a|admin)$"))
@router.message(F.text.casefold().contains("модерация"))
async def cmd_moderator_panel(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager) -> None:
    admin_svc = AdminService(session=session)
    if not await admin_svc.is_admin_strictly(message.from_user.id):
        return
    await on_enter_moderator_panel(message, session, ui, state)


# --- ВЛАДЕЛЕЦ (Команда /o или /owner) ---

async def on_enter_owner_panel(event: Message | CallbackQuery, session: AsyncSession, ui: MessageManager, state: FSMContext | None = None) -> None:
    """Центральный вход в панель владельца."""
    logger.info(f"Owner {event.from_user.id} entering dashboard")
    if state:
        await state.clear()
        
    from src.domain.moderation.admin_stats_service import AdminStatsService
    stats_svc = AdminStatsService(session)
    
    try:
        logger.debug("Fetching owner summary stats...")
        stats = await stats_svc.get_owner_summary_stats()
        
        # Дополнительно считаем % зачета за 24ч для дашборда
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        logger.debug("Fetching platform stats for last 24h...")
        platform_stats = await stats_svc.get_platform_stats(start, datetime.now(timezone.utc))
        stats["accept_rate"] = platform_stats["reject_rate"] # В платформе это reject_rate, инвертируем или используем как есть
        
        stats["username"] = event.from_user.username or str(event.from_user.id)
        
        logger.debug("Rendering dashboard text...")
        text = _renderer.render_owner_dashboard(stats)
        
        kb = await get_owner_main_kb()
        await ui.display(event=event, text=text, reply_markup=kb)
        logger.info(f"Dashboard displayed for {event.from_user.id}")
    except Exception as e:
        logger.error(f"Failed to enter owner panel: {e}", exc_info=True)
        # Если мы здесь, значит LoadingMiddleware поймает исключение и покажет ошибку.
        raise e

@router.message(Command("o", "owner"), IsOwnerFilter())
async def cmd_owner_panel(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager) -> None:
    await on_enter_owner_panel(message, session, ui, state)

@router.callback_query(F.data == "admin_moderation")
async def cb_admin_moderation_redirect(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Редирект старого колбэка на новый формат."""
    await on_enter_moderator_panel(callback, session, ui, state)
    await callback.answer()


from src.presentation.common.factory import NavCD


@router.callback_query(NavCD.filter(F.to == "admin_menu"))
async def back_to_admin_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager) -> None:
    await state.clear()
    admin_svc = AdminService(session=session)
    
    # Если это владелец, по умолчанию возвращаем в его кабинет
    if await admin_svc.is_owner_strictly(callback.from_user.id):
        await on_enter_owner_panel(callback, session, ui, state)
    # Если это админ, возвращаем в панель модератора
    elif await admin_svc.is_admin_strictly(callback.from_user.id):
        await on_enter_moderator_panel(callback, session, ui, state)
    else:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
    await callback.answer()


router.include_router(owner_cabinet_router)

__all__ = ["router", "on_enter_moderator_panel", "on_enter_owner_panel"]
