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
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import UserRole
from src.presentation.common.factory import QRDeliveryCD, NavCD
from .keyboards import get_qr_delivery_main_kb, get_qr_delivery_operators_kb, get_qr_delivery_webapp_kb
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.presentation.qr_delivery.states import QRDeliveryStates
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.core.utils.message_manager import MessageManager

router = Router(name="qr-delivery-router")
logger = logging.getLogger(__name__)

from src.presentation.filters.admin import IsAdminFilter, IsOwnerFilter

# --- ГЛАВНОЕ МЕНЮ ВЫДАЧИ ---

@router.message(Command("qr"), StateFilter("*"))
@router.callback_query(QRDeliveryCD.filter(F.action == "menu"))
@router.callback_query(F.data == "qr_delivery_menu")
async def cmd_qr_delivery_menu(event: Message | CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager, bot: Bot, **data):
    """Классическое меню (кнопки)."""
    logger.info(f"DEBUG: cmd_qr_delivery_menu TRIGGERED by {event.from_user.id}")
    if isinstance(event, CallbackQuery):
        chat_id = event.message.chat.id
        thread_id = getattr(event.message, "message_thread_id", None)
    else:
        chat_id = event.chat.id
        thread_id = getattr(event, "message_thread_id", None)

    try:
        logger.info(f"User {event.from_user.id} accessing /qr in chat {chat_id} (thread {thread_id})")
        await state.clear()
        
        from src.domain.users.user_service import UserService
        user = await UserService(session=session).get_by_telegram_id(event.from_user.id)
        
        if not user or user.role not in (UserRole.ADMIN, UserRole.OWNER, UserRole.SIMBUYER):
            role_info = user.role if user else 'NOT REGISTERED'
            msg = f"❌ <b>ОТКАЗАНО:</b> Доступ запрещен (Ваша роль: <code>{role_info}</code>)"
            if isinstance(event, CallbackQuery): await event.answer(msg, show_alert=True)
            else: await bot.send_message(chat_id, msg, parse_mode="HTML", message_thread_id=thread_id)
            return

        text = (
            f"❖ <b>GDPX // СИСТЕМА ВЫДАЧИ</b>\n"
            f"{DIVIDER}\n"
            f"Инструментарий для оперативной отгрузки eSIM.\n\n"
            f"<i>Это меню изолировано для вас. Другие админы его не увидят.</i>"
        )
        
        await ui.display(event=event, text=text, reply_markup=get_qr_delivery_main_kb())
        if isinstance(event, CallbackQuery):
            await event.answer()
            
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in /qr: {e}")
        error_msg = f"⚠️ <b>ОШИБКА ВЫДАЧИ:</b>\n<code>{str(e)}</code>"
        await bot.send_message(chat_id, error_msg, parse_mode="HTML", message_thread_id=thread_id)

@router.message(Command("qrweb"), StateFilter("*"))
async def cmd_qr_delivery_web(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager, bot: Bot):
    """Вход в современный DELIVERY HUB (WebApp)."""
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    try:
        logger.info(f"User {message.from_user.id} attempting to access /qrweb")
        await state.clear()
        
        from src.domain.users.user_service import UserService
        user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
        
        if not user or user.role not in (UserRole.ADMIN, UserRole.OWNER, UserRole.SIMBUYER):
            return await message.answer(f"❌ <b>ОТКАЗАНО:</b> Недостаточно прав.", parse_mode="HTML")

        text = (
            f"❖ <b>GDPX // DELIVERY HUB</b>\n"
            f"{DIVIDER}\n"
            f"Современный интерфейс для управления отгрузками.\n\n"
            f"<i>Нажмите кнопку ниже для запуска приложения:</i>"
        )
        
        await ui.display(event=message, text=text, reply_markup=get_qr_delivery_webapp_kb(message.chat.id))
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in /qrweb: {e}")
        await message.answer(f"⚠️ <b>ОШИБКА HUB:</b>\n<code>{str(e)}</code>", parse_mode="HTML")

@router.callback_query(QRDeliveryCD.filter(F.action == "op_list"))
async def cb_delivery_op_list(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Список операторов с доступным стоком."""
    sub_svc = SubmissionService(session=session)
    stats = await sub_svc.get_warehouse_stats_grouped()
    
    if not stats:
        return await callback.answer("📭 Склад пуст.", show_alert=True)

    text = (
        f"❖ <b>GDPX // ВЫБОР ОПЕРАТОРА</b>\n"
        f"{DIVIDER_LIGHT}\n"
        f"Ниже список категорий, в которых есть готовых eSIM."
    )
    
    # Сначала удаляем текущее меню, чтобы создать новое "чистое"
    await ui.delete_main(event=callback)
    await ui.display(event=callback, text=text, reply_markup=get_qr_delivery_operators_kb(stats))
    await callback.answer()

@router.callback_query(QRDeliveryCD.filter(F.action == "op_pick"))
async def cb_delivery_op_pick(callback: CallbackQuery, callback_data: QRDeliveryCD, state: FSMContext, session: AsyncSession, ui: MessageManager):
    """Запрос количества для выдачи."""
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
    
    from src.presentation.common.base import PremiumBuilder
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
    
    # 1. Сначала удаляем интерфейсное сообщение и сообщение пользователя
    await ui.delete_main(event=message)
    try: await message.delete()
    except: pass

    # 2. Показываем временный статус
    wait_msg = await message.answer("⏳ <b>Инициация отгрузки...</b>", parse_mode="HTML")

    sub_svc = SubmissionService(session=session)
    items = await sub_svc.take_from_warehouse(cat_id, count)
    
    if not items:
        return await wait_msg.edit_text("🔴 Ошибка извлечения активов.")

    success_count = 0
    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # 3. Выдача активов
    for item in items:
        try:
            caption = (
                f"❖ <b>GDPX // eSIM #{item.id}</b>\n"
                f"{DIVIDER_LIGHT}\n"
                f"📶 <b>ОПЕРАТОР:</b> {data['cat_title']}\n"
                f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                f"👤 <b>АГЕНТ:</b> @{item.seller.username or 'id' + str(item.seller.telegram_id)}"
            )
            
            if item.attachment_type == "photo":
                await bot.send_photo(chat_id, item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            else:
                await bot.send_document(chat_id, item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            
            success_count += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error delivery item {item.id}: {e}")

    await session.commit()
    await wait_msg.delete()

    # 4. Отправляем свежее главное меню как завершающий штрих
    user_mention = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
    text = (
        f"✅ Выдано <code>{success_count}</code> шт. сканов по запросу <b>{user_mention}</b>\n\n"
        f"Удачной отработки!\n"
        f"{DIVIDER}\n"
        f"<i>Интерфейс выдачи обновлен.</i>"
    )
    await ui.display(event=message, text=text, reply_markup=get_qr_delivery_main_kb())

@router.callback_query(QRDeliveryCD.filter(F.action == "cancel"), StateFilter("*"))
async def cb_delivery_cancel(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Полное закрытие меню выдачи."""
    await state.clear()
    await ui.delete_main(event=callback)
    await callback.answer("🚪 Меню закрыто")
