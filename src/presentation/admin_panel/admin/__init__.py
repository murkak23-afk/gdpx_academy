from __future__ import annotations

import asyncio
from aiogram import F, Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import Submission
from src.database.models.user import User
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

@router.message(Command("maintenance"), IsOwnerFilter())
async def cmd_maintenance_toggle(message: Message, command: CommandObject, session: AsyncSession, bot: Bot):
    from src.core.config import get_settings
    settings = get_settings()
    arg = command.args
    
    if arg == "on":
        settings.maintenance_mode = True
        await message.answer("🚧 <b>РЕЖИМ ТЕХРАБОТ ВКЛЮЧЕН</b>\nДоступ для селлеров ограничен.", parse_mode="HTML")
    elif arg == "off":
        settings.maintenance_mode = False
        await message.answer("✅ <b>РЕЖИМ ТЕХРАБОТ ВЫКЛЮЧЕН</b>\nБот доступен для всех. Запускаю уведомление селлеров...", parse_mode="HTML")
        
        # Запускаем рассылку всем селлерам
        try:
            from src.domain.users.user_service import UserService
            from src.core.broadcaster import broadcast
            from src.core.utils.ui_builder import DIVIDER
            
            user_svc = UserService(session)
            # Получаем всех активных селлеров
            stmt = select(User.telegram_id).where(User.role == UserRole.SELLER)
            res = await session.execute(stmt)
            user_ids = [r for r in res.scalars().all()]
            
            broadcast_text = (
                "🔋 <b>ТЕРМИНАЛ ВОССТАНОВЛЕН</b>\n"
                f"{DIVIDER}\n"
                "Технические работы завершены. Доступ к системе полностью открыт.\n\n"
                "🤝 <i>Благодарим за терпение. Удачных загрузок!</i>"
            )
            
            # Запускаем в фоне, чтобы не вешать хендлер
            asyncio.create_task(broadcast(bot, user_ids, broadcast_text))
            logger.info(f"Started maintenance-off broadcast to {len(user_ids)} users")
            
        except Exception as e:
            logger.error(f"Failed to start maintenance-off broadcast: {e}")
    else:
        status = "ВКЛЮЧЕН 🚧" if settings.maintenance_mode else "ВЫКЛЮЧЕН ✅"
        await message.answer(f"Текущий статус техработ: <b>{status}</b>\nИспользуйте: <code>/maintenance on</code> или <code>off</code>", parse_mode="HTML")

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
