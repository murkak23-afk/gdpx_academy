# ruff: noqa: F401
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import DIVIDER
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import Submission
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import QRDeliveryCD
from src.presentation.qr_delivery.states import QRDeliveryStates
from .keyboards import get_qr_delivery_main_kb, get_qr_delivery_operators_kb, get_qr_delivery_webapp_kb

router = Router(name="qr-delivery-router")
logger = logging.getLogger(__name__)

# --- AUTO FIX LOGIC (Автоматическая фиксация статуса) ---

@router.message(F.chat.id.in_(get_settings().auto_fix_chats.keys()), F.text)
async def handle_auto_fix_message(message: Message, session: AsyncSession):
    """
    Слушает сообщения в топиках авто-блока и меняет статус сим-карт.
    Работает в чатах, указанных в AUTO_FIX_CHATS.
    """
    settings = get_settings()
    chat_configs = settings.auto_fix_chats.get(message.chat.id)
    if not chat_configs:
        return

    # Определяем действие по топику (Blocked / Not a scan)
    topic_id = message.message_thread_id or 0
    action_type = chat_configs.get(topic_id)
    if not action_type:
        return

    # Извлекаем все цифры (номер телефона)
    digits = "".join(filter(str.isdigit, message.text))
    if len(digits) < 4:
        return # Слишком короткий номер для поиска

    target_status = SubmissionStatus.BLOCKED if action_type == "blocked" else SubmissionStatus.NOT_A_SCAN
    found_sub = None
    search_method = "FULL"

    # 1. Сначала ищем по полному номеру (11 цифр)
    if len(digits) == 11:
        stmt = select(Submission).where(
            Submission.phone_normalized == digits,
            Submission.status == SubmissionStatus.IN_WORK
        ).order_by(Submission.updated_at.desc())
        found_sub = (await session.execute(stmt)).scalar_one_or_none()
    
    # 2. Если не нашли по полному или цифр меньше 11, ищем по суффиксу (последние 4 цифры)
    if not found_sub and len(digits) >= 4:
        search_method = "SUFFIX"
        stmt = select(Submission).where(
            Submission.phone_normalized.like(f"%{digits[-4:]}"),
            Submission.status == SubmissionStatus.IN_WORK
        ).order_by(Submission.updated_at.desc())
        results = (await session.execute(stmt)).scalars().all()
        
        if len(results) == 1:
            found_sub = results[0]
        elif len(results) > 1:
            return await message.reply(f"⚠️ Найдено несколько совпадений ({len(results)}) по суффиксу. Уточните номер.")

    # 3. Применяем статус, если нашли актив
    if found_sub:
        found_sub.status = target_status
        await session.commit()
        
        await message.reply(
            f"✅ <b>AUTO-FIX:</b> Статус изменен\n"
            f"📟 ID: <code>{found_sub.id}</code>\n"
            f"📞 Номер: <code>{found_sub.phone_normalized}</code>\n"
            f"⚙️ Метод: <code>{search_method}</code>\n"
            f"🔄 Статус: <code>{target_status.upper()}</code>",
            parse_mode="HTML"
        )
        logger.info(f"AUTO_FIX: Sub #{found_sub.id} set to {target_status} via chat {message.chat.id}")
    elif len(digits) == 11:
        # Уведомляем только если был полноценный номер, но его нет в базе
        await message.reply("❌ Номер не найден среди выданных в работу (IN_WORK).")

# --- ГЛАВНОЕ МЕНЮ ВЫДАЧИ ---

@router.message(Command("qr"), StateFilter("*"))
@router.callback_query(QRDeliveryCD.filter(F.action == "menu"), StateFilter("*"))
@router.callback_query(F.data == "qr_delivery_menu", StateFilter("*"))
async def cmd_qr_delivery_menu(event: Message | CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Главное меню (только кнопки)."""
    logger.debug(f"DEBUG_QR: Menu called by {event.from_user.id}")
    await state.clear()
    
    user_svc = UserService(session=session)
    user = await user_svc.get_by_telegram_id(event.from_user.id)
    
    if not user or user.role not in (UserRole.ADMIN, UserRole.OWNER, UserRole.SIMBUYER):
        if isinstance(event, CallbackQuery): await event.answer("❌ Доступ ограничен", show_alert=True)
        return

    text = (
        f"❖ <b>GDPX // СИСТЕМА ВЫДАЧИ</b>\n"
        f"{DIVIDER}\n"
        f"Инструментарий для оперативной отгрузки eSIM (КНОПКИ).\n\n"
        f"<i>Выберите оператора для начала процесса:</i>"
    )
    
    await ui.display(event=event, text=text, reply_markup=get_qr_delivery_main_kb())
    if isinstance(event, CallbackQuery): await event.answer()

@router.message(Command("qrweb"), StateFilter("*"))
async def cmd_qr_delivery_web(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Вход в DELIVERY HUB (WebApp)."""
    await state.clear()
    user_svc = UserService(session=session)
    user = await user_svc.get_by_telegram_id(message.from_user.id)
    
    if not user or user.role not in (UserRole.ADMIN, UserRole.OWNER, UserRole.SIMBUYER):
        return

    text = (
        f"❖ <b>GDPX // DELIVERY HUB</b>\n"
        f"{DIVIDER}\n"
        f"Современный интерфейс для управления отгрузками.\n\n"
        f"<i>Нажмите кнопку ниже для запуска приложения:</i>"
    )
    
    await ui.display(event=message, text=text, reply_markup=get_qr_delivery_webapp_kb(message.chat.id))

@router.callback_query(QRDeliveryCD.filter(F.action == "op_list"), StateFilter("*"))
async def cb_delivery_op_list(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Список операторов с доступным стоком."""
    logger.debug(f"DEBUG_QR: op_list by {callback.from_user.id}")
    sub_svc = SubmissionService(session=session)
    stats = await sub_svc.get_warehouse_stats_grouped()
    
    if not stats:
        return await callback.answer("📭 Склад пуст.", show_alert=True)

    text = (
        f"❖ <b>ВЫБОР ОПЕРАТОРА</b>\n"
        f"{DIVIDER}\n"
        f"Ниже список категорий, в которых есть готовые к выдаче eSIM (PENDING)."
    )
    
    await ui.display(event=callback, text=text, reply_markup=get_qr_delivery_operators_kb(stats))
    await callback.answer()

@router.callback_query(QRDeliveryCD.filter(F.action == "op_pick"), StateFilter("*"))
async def cb_delivery_op_pick(callback: CallbackQuery, callback_data: QRDeliveryCD, state: FSMContext, session: AsyncSession, ui: MessageManager):
    """Запрос количества для выдачи."""
    logger.debug(f"DEBUG_QR: op_pick {callback_data.val} by {callback.from_user.id}")
    cat_id = int(callback_data.val)
    
    from src.domain.submission.category_service import CategoryService
    cat = await CategoryService(session=session).get_by_id(cat_id)
    
    sub_svc = SubmissionService(session=session)
    available = await sub_svc.get_category_stock_count(cat_id)
    
    if available <= 0:
        return await callback.answer("❌ Активы закончились.", show_alert=True)

    await state.update_data(cat_id=cat_id, cat_title=cat.title, available=available)
    await state.set_state(QRDeliveryStates.waiting_for_count)
    
    text = (
        f"📶 <b>ОПЕРАТОР:</b> {cat.title}\n"
        f"📦 <b>ДОСТУПНО:</b> <code>{available}</code> шт.\n"
        f"{DIVIDER}\n"
        f"Введите количество eSIM для выдачи (числом):"
    )
    
    kb = PremiumBuilder().back(QRDeliveryCD(action="op_list")).as_markup()
    await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()

@router.message(QRDeliveryStates.waiting_for_count, F.text)
async def process_delivery_count(message: Message, state: FSMContext, session: AsyncSession, bot: Bot, ui: MessageManager):
    """Выдача eSIM прямо в чат/топик."""
    data = await state.get_data()
    cat_id, available = data['cat_id'], data['available']
    
    try:
        count = int(message.text.strip())
        if count <= 0: raise ValueError
    except:
        return await message.answer("❌ Введите положительное число.")

    if count > available:
        return await message.answer(f"❌ Доступно только: {available}")

    await state.clear()
    wait_msg = await message.answer("⏳ <b>Инициация отгрузки...</b>", parse_mode="HTML")

    sub_svc = SubmissionService(session=session)
    items = await sub_svc.take_from_warehouse(cat_id, count)
    
    if not items:
        return await wait_msg.edit_text("🔴 Ошибка извлечения активов.")

    success_count = 0
    for item in items:
        try:
            caption = (
                f"📟 <b>eSIM #{item.id}</b>\n"
                f"📶 <b>ОПЕРАТОР:</b> {data['cat_title']}\n"
                f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                f"{DIVIDER}\n"
                f"👤 <b>АГЕНТ:</b> @{item.seller.username or 'id' + str(item.seller.telegram_id)}"
            )
            thread_id = message.message_thread_id
            if item.attachment_type == "photo":
                await bot.send_photo(message.chat.id, item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            else:
                await bot.send_document(message.chat.id, item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            
            success_count += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error delivery item {item.id}: {e}")

    await wait_msg.delete()
    await message.answer(
        f"✅ <b>ОТГРУЗКА ЗАВЕРШЕНА</b>\n"
        f"{DIVIDER}\n"
        f"Выдано: <code>{success_count}</code> шт.\n"
        f"Статус изменен на <b>IN_WORK</b>.",
        parse_mode="HTML",
        reply_markup=get_qr_delivery_main_kb()
    )

@router.callback_query(QRDeliveryCD.filter(F.action == "cancel"), StateFilter("*"))
async def cb_delivery_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession, ui: MessageManager):
    """Отмена операции выдачи."""
    await state.clear()
    await cmd_qr_delivery_menu(callback, session, state, ui)
