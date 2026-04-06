from __future__ import annotations

import logging
import re
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.admin_service import AdminService
from src.services.submission_service import SubmissionService
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus
from src.utils.ui_builder import GDPXRenderer
from src.keyboards.factory import AdminMenuCD, AdminQueueCD, NavCD
from src.keyboards.builders import get_admin_main_kb, get_admin_queue_lobby_kb, get_admin_back_kb
from src.utils.text_format import edit_message_text_or_caption_safe, edit_message_text_safe

# Импорты для делегирования
from src.handlers.admin.payouts import on_daily_report
from src.handlers.moderation import on_moderation_queue

router = Router(name="admin-menu-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# Константы для совместимости
PHONE_QUERY_PATTERN = r"^[+\d][\d \-()]{6,24}$"
SELLERS_PAGE_SIZE = 10

# --- Функции для совместимости с внешними модулями ---

async def render_admin_moderation_card(submission: Submission, session: AsyncSession) -> str:
    """Публичный метод для отрисовки карточки."""
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

# Совместимость со старым именем (с подчеркиванием)
_render_admin_moderation_card = render_admin_moderation_card

async def on_admin_panel(message: Message, session: AsyncSession) -> None:
    await cmd_admin_panel(message, session)

async def on_enter_admin_panel(event: Message | CallbackQuery, session: AsyncSession) -> None:
    if isinstance(event, Message):
        await cmd_admin_panel(event, session)
    else:
        stats = await _fetch_admin_board_stats(session)
        stats["username"] = event.from_user.username or str(event.from_user.id)
        text = _renderer.render_admin_dashboard(stats)
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=get_admin_main_kb())

async def on_exit_admin_panel(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Выход из системы.")

async def on_admin_menu_interrupt_fsm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await on_enter_admin_panel(callback, session)

async def on_admin_fsm_step_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await on_enter_admin_panel(callback, session)

# --- Вспомогательная логика ---

def _group_submissions_by_seller(submissions: list[Submission]) -> list[dict]:
    groups = {}
    for s in submissions:
        uid = s.user_id
        if uid not in groups:
            # Пытаемся взять seller из объекта, если он подгружен
            username = getattr(s.seller, "username", None) if hasattr(s, "seller") else None
            label = f"@{username}" if username else f"ID:{uid}"
            groups[uid] = {"user_id": uid, "label": label, "count": 0}
        groups[uid]["count"] += 1
    return sorted(groups.values(), key=lambda x: x["count"], reverse=True)

async def _fetch_admin_board_stats(session: AsyncSession) -> dict:
    pending = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING))
    in_review = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW))
    accepted = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.ACCEPTED))
    rejected = await session.scalar(select(func.count(Submission.id)).where(Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED])))
    
    return {
        "pending_count": pending or 0,
        "in_review_count": in_review or 0,
        "approved_count": accepted or 0,
        "rejected_count": rejected or 0,
    }

# --- Основные обработчики ---

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

@router.callback_query(AdminMenuCD.filter(F.section == "queue"))
async def admin_queue_lobby(callback: CallbackQuery, session: AsyncSession) -> None:
    pending_count = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING))
    text = _renderer.render_queue_lobby(pending_count=pending_count or 0)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_admin_queue_lobby_kb())
    await callback.answer()

@router.callback_query(AdminQueueCD.filter(F.action == "start"))
async def admin_queue_start(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer("Запуск буфера...")
    await callback.message.delete()
    await on_moderation_queue(callback.message, session, _caller_id=callback.from_user.id)

@router.callback_query(AdminMenuCD.filter(F.section == "inwork"))
async def admin_inwork_hub(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    await state.clear()
    groups = _group_submissions_by_seller(all_subs)
    
    text = _renderer.render_inwork_sellers(
        groups[:SELLERS_PAGE_SIZE], 
        total_sellers=len(groups), 
        total_cards=len(all_subs)
    )
    await edit_message_text_safe(callback.message, text, reply_markup=get_admin_back_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(AdminMenuCD.filter(F.section == "payouts"))
async def admin_payouts(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("❌ Нет доступа к выплатам", show_alert=True)
        return
    await callback.answer()
    await on_daily_report(callback.message, state, session, _caller_id=callback.from_user.id)

@router.callback_query(AdminMenuCD.filter(F.section == "search"))
async def admin_search_start(callback: CallbackQuery) -> None:
    await callback.answer("Функция поиска SIM активна. Используйте /sim [номер]", show_alert=True)

@router.callback_query(AdminMenuCD.filter(F.section == "stats"))
async def admin_stats_menu(callback: CallbackQuery) -> None:
    await callback.answer("Раздел аналитики в разработке", show_alert=True)

@router.callback_query(AdminMenuCD.filter(F.section == "broadcast"))
async def admin_broadcast_start(callback: CallbackQuery) -> None:
    await callback.answer("Рассылка: используйте команду /broadcast", show_alert=True)
