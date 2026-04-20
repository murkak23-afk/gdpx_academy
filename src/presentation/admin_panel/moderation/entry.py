from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.factory import AdminMenuCD, AdminQueueCD
from .keyboards import get_mod_dashboard_kb, get_sellers_queue_kb, get_seller_workspace_kb
from src.domain.moderation.moderation_service import ModerationService
from src.domain.users.user_service import UserService
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT

router = Router(name="moderation-entry-router")


def _generate_progress_bar(current: int, total: int) -> str:
    """Генерирует премиум прогресс-бар."""
    if total <= 0:
        return "▒" * 10
    percent = min(100, int((current / total) * 100))
    filled = int(percent / 10)
    return "█" * filled + "▒" * (10 - filled)


async def _render_dashboard_text(session: AsyncSession, user_id: int) -> tuple[str, dict]:
    """Сборка дашборда Реформы Модерации."""
    mod_service = ModerationService(session=session)
    stats = await mod_service.get_reform_stats()
    
    from src.core.config import get_settings
    settings = get_settings()
    
    status_warning = ""
    if getattr(settings, "moderation_suspended", False):
        status_warning = f"⚠️ <b>ВНИМАНИЕ: РАБОТА ПРИОСТАНОВЛЕНА ВЛАДЕЛЬЦЕМ</b>\n{DIVIDER_LIGHT}\n"

    text = (
        f"❖ <b>GDPX // ЦЕНТР УПРАВЛЕНИЯ МОДЕРАЦИЕЙ</b>\n"
        f"{DIVIDER}\n"
        f"{status_warning}"
        f"🚀 <b>СКЛАД (NEW):</b> <code>{stats['warehouse']}</code> шт.\n"
        f"📟 <b>ВЫДАННЫЕ (В РАБОТЕ):</b> <code>{stats['issued']}</code> шт.\n"
        f"✨ <b>ПРОВЕРКА (ЖДУТ):</b> <code>{stats['verification']}</code> шт.\n"
        f"🚫 <b>БЛОКНУТЫЕ (24H):</b> <code>{stats['blocked']}</code> шт.\n"
        f"{DIVIDER_LIGHT}\n"
        f"<i>⚡ Выберите раздел для управления активами:</i>"
    )
    return text, stats


@router.callback_query(AdminMenuCD.filter(F.section == "moderation"))
@router.callback_query(F.data == "mod_back_dash")
async def cmd_moderation_dashboard_cb(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager):
    await state.clear()
    text, stats = await _render_dashboard_text(session, callback.from_user.id)
    await ui.display(event=callback, text=text, reply_markup=get_mod_dashboard_kb(stats))
    await callback.answer()


@router.callback_query(F.data == "mod_issued_folder")
async def open_issued_folder(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Раздел 'Выданные' (все IN_WORK)."""
    mod_service = ModerationService(session=session)
    stats = await mod_service.get_reform_stats()
    
    text = (
        f"❖ <b>ВЫДАННЫЕ АКТИВЫ</b>\n"
        f"{DIVIDER}\n"
        f"Всего на руках у покупателей: <code>{stats['issued']}</code> шт.\n\n"
        f"Здесь отображаются все симки в статусе «В работе»."
    )
    from .keyboards import get_sellers_queue_kb
    sellers_data = await mod_service.get_pending_sellers(status=["in_work"])
    await ui.display(event=callback, text=text, reply_markup=get_sellers_queue_kb(sellers_data, status="in_work"))
    await callback.answer()


@router.callback_query(F.data == "mod_queue_folder")
async def open_queue_folder(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Раздел 'Склад' (новые PENDING)."""
    mod_service = ModerationService(session=session)
    stats = await mod_service.get_queue_stats()
    
    text = (
        f"❖ <b>GDPX // СКЛАД АКТИВОВ</b>\n"
        f"{DIVIDER}\n"
        f"На складе ожидает: <code>{stats['warehouse']}</code> новых активов.\n\n"
        f"Здесь находятся новые заявки от всех агентов, ожидающие выдачи.\n\n"
        f"<i>Выберите способ работы:</i>"
    )
    from .keyboards import get_sellers_queue_kb
    sellers_data = await mod_service.get_pending_sellers(status=["pending"])
    await ui.display(event=callback, text=text, reply_markup=get_sellers_queue_kb(sellers_data, status="pending"))
    await callback.answer()


@router.callback_query(F.data == "mod_waiting_folder")
@router.callback_query(AdminQueueCD.filter(F.action == "verification"))
async def open_waiting_confirmation(callback: CallbackQuery, session: AsyncSession, ui: MessageManager, callback_data: AdminQueueCD | None = None):
    """Раздел 'Проверка' (WAIT_CONFIRM + IN_REVIEW) с пагинацией."""
    page = callback_data.page if callback_data else 0
    page_size = 10
    
    mod_service = ModerationService(session=session)
    # Используем список селлеров для единообразия, либо карточки айтемов
    # В новой структуре лучше показывать список селлеров, у которых есть verification
    sellers_data = await mod_service.get_pending_sellers(status=["wait_confirm", "in_review"])
    
    text = (
        f"❖ <b>GDPX // ПРОВЕРКА АКТИВОВ</b>\n"
        f"{DIVIDER}\n"
        f"Ниже список селлеров, чьи активы требуют ручного зачёта.\n"
        f"💎 <b>ВСЕГО СЕЛЛЕРОВ:</b> <code>{len(sellers_data)}</code>"
    )
    from .keyboards import get_sellers_queue_kb
    await ui.display(
        event=callback, 
        text=text, 
        reply_markup=get_sellers_queue_kb(sellers_data, status="verification")
    )
    await callback.answer()


@router.callback_query(F.data == "mod_blocked_folder")
async def open_blocked_folder(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Раздел 'Блокнутые' (BLOCKED/NOT_A_SCAN за последние 24 часа)."""
    logger.info(f"Admin {callback.from_user.id} opening blocked folder")
    try:
        mod_service = ModerationService(session=session)
        logger.debug("Fetching recent blocked grouped items...")
        blocked_items = await mod_service.get_recent_blocked_grouped()
        logger.debug(f"Found {len(blocked_items)} blocked groups")

        if not blocked_items:
            return await callback.answer("✨ За последние 24 часа блокировок не было.", show_alert=True)

        lines = [
            "❖ <b>БЛОКНУТЫЕ АКТИВЫ (24H)</b>",
            f"{DIVIDER}",
            "<i>Группировка по продавцам и операторам:</i>\n"
        ]

        current_seller = None
        for item in blocked_items:
            if item['seller'] != current_seller:
                current_seller = item['seller']
                lines.append(f"👤 <b>@{current_seller}</b>")

            status_icon = "🚫" if item['status'] == "БЛОК" else "📵"
            lines.append(f" ├ {status_icon} {item['operator']}: <code>{item['count']}</code> шт.")

        from .keyboards import get_blocked_list_kb
        await ui.display(event=callback, text="\n".join(lines), reply_markup=get_blocked_list_kb())
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in open_blocked_folder: {e}", exc_info=True)
        raise e


@router.callback_query(F.data == "mod_take_all_waiting")
async def mod_take_all_waiting(callback: CallbackQuery, session: AsyncSession, bot: Bot, ui: MessageManager, state: FSMContext):
    """Массовый зачёт всех 'отработанных' симок (>1 часа в работе)."""
    mod_service = ModerationService(session=session)
    user_svc = UserService(session=session)
    admin = await user_svc.get_by_telegram_id(callback.from_user.id)

    items = await mod_service.get_waiting_confirmation_items(limit=100)
    if not items:
        return await callback.answer("✨ Список пуст.", show_alert=True)

    from src.database.models.enums import SubmissionStatus
    count = await mod_service.bulk_finalize_submissions(
        submission_ids=[i.id for i in items],
        status=SubmissionStatus.ACCEPTED,
        admin_id=admin.id,
        bot=bot
    )

    await callback.answer(f"✅ Успешно зачтено: {count} шт.", show_alert=True)
    await cmd_moderation_dashboard_cb(callback, session, state, ui) # Refresh dash
