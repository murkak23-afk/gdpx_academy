from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.moderation_service import ModerationService
from src.services.admin_service import AdminService
from src.keyboards.moderation import get_mod_dashboard_kb
from src.keyboards.factory import AdminMenuCD
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="moderation-entry-router")


def _generate_progress_bar(current: int, total: int) -> str:
    """Генерирует премиум прогресс-бар."""
    if total <= 0:
        return "▒" * 10
    percent = min(100, int((current / total) * 100))
    filled = int(percent / 10)
    return "█" * filled + "▒" * (10 - filled)


async def _render_dashboard_text(session: AsyncSession, user_id: int) -> tuple[str, int, int]:
    """Сборка премиум-дашборда с личной статистикой."""
    from src.services.user_service import UserService
    user = await UserService(session=session).get_by_telegram_id(user_id)
    
    mod_service = ModerationService(session=session)
    stats = await mod_service.get_queue_stats()
    
    in_work = 0
    my_accepted = 0
    my_rejected = 0
    
    if user:
        in_work = await mod_service.get_my_active_items(user.id)
        my_accepted, my_rejected = await mod_service.get_admin_daily_stats(user.id)
    
    total_processed = stats['processed_today']
    total_target = max(1, total_processed + stats['total_pending'])
    progress = _generate_progress_bar(total_processed, total_target)
    percent = min(100, int((total_processed / total_target) * 100)) if total_target > 0 else 0

    text = (
        f"❖ <b>GDPX // ЦЕНТР УПРАВЛЕНИЯ МОДЕРАЦИЕЙ</b>\n"
        f"{DIVIDER}\n"
        f"📦 <b>Общая очередь:</b> <code>{stats['total_pending']}</code> активов\n"
        f"🏃 <b>У вас в работе:</b> <code>{in_work}</code> шт.\n"
        f"{DIVIDER_LIGHT}\n"
        f"📊 <b>ПРОГРЕСС СЕТИ ЗА 24H:</b>\n"
        f"<code>{progress}</code> {percent}%\n"
        f"<i>(Обработано: {total_processed} шт.)</i>\n\n"
        f"👤 <b>ВАША ПРОДУКТИВНОСТЬ СЕГОДНЯ:</b>\n"
        f" ├ ✅ Зачётов: <code>{my_accepted}</code>\n"
        f" └ ❌ Отказов: <code>{my_rejected}</code>\n\n"
        f"<i>⚡ Выберите инструмент для продолжения работы:</i>"
    )
    return text, stats['total_pending'], in_work


@router.message(F.text.casefold().contains("модерация"))
async def cmd_moderation_dashboard_msg(message: Message, session: AsyncSession):
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    text, pending, in_work = await _render_dashboard_text(session, message.from_user.id)
    await message.answer(text, reply_markup=get_mod_dashboard_kb(pending, in_work), parse_mode="HTML")


@router.callback_query(AdminMenuCD.filter(F.section == "moderation"))
@router.callback_query(F.data == "mod_back_dash")
async def cmd_moderation_dashboard_cb(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()  # Чистим состояние при входе в дашборд

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        return
    text, pending, in_work = await _render_dashboard_text(session, callback.from_user.id)
    await edit_message_text_or_caption_safe(
        callback.message, 
        text, 
        reply_markup=get_mod_dashboard_kb(pending, in_work),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "mod_my_work_folder")
async def open_my_work_folder(callback: CallbackQuery, session: AsyncSession):
    """Открывает папку действий с личными активами."""
    text = (
        f"❖ <b>GDPX // ВАШИ АКТИВЫ</b>\n"
        f"{DIVIDER}\n"
        f"Здесь находятся активы, которые вы уже взяли в работу, но еще не приняли по ним решение.\n\n"
        f"<i>Выберите режим работы:</i>"
    )
    from src.keyboards.moderation import get_my_work_folder_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_my_work_folder_kb(), parse_mode="HTML")
    await callback.answer()
    

@router.callback_query(F.data == "mod_queue_folder")
async def open_queue_folder(callback: CallbackQuery, session: AsyncSession):
    """Открывает папку действий с общей очередью."""
    text = (
        f"❖ <b>GDPX // ОБЩАЯ ОЧЕРЕДЬ</b>\n"
        f"{DIVIDER}\n"
        f"Здесь находятся новые заявки от всех агентов, ожидающие проверки.\n\n"
        f"<i>Выберите, как вы хотите с ними работать:</i>"
    )
    from src.keyboards.moderation import get_queue_folder_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_queue_folder_kb(), parse_mode="HTML")
    await callback.answer()
