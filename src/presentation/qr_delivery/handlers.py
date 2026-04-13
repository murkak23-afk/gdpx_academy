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
from .keyboards import get_qr_delivery_main_kb, get_qr_delivery_operators_kb
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.presentation.qr_delivery.states import QRDeliveryStates
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.core.utils.message_manager import MessageManager

router = Router(name="qr-delivery-router")
logger = logging.getLogger(__name__)

# --- ГЛАВНОЕ МЕНЮ ВЫДАЧИ ---

@router.message(Command("qr"), StateFilter("*"))
@router.callback_query(QRDeliveryCD.filter(F.action == "menu"))
@router.callback_query(F.data == "qr_delivery_menu")
async def cmd_qr_delivery_menu(event: Message | CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Главный экран системы выдачи (поддерживает группы и топики)."""
    await state.clear()
    
    user_svc = UserService(session=session)
    user = await user_svc.get_by_telegram_id(event.from_user.id)
    
    if not user or user.role not in (UserRole.ADMIN, UserRole.OWNER, UserRole.SIMBUYER):
        if isinstance(event, CallbackQuery):
            await event.answer("❌ Доступ ограничен", show_alert=True)
        return

    text = (
        f"❖ <b>GDPX // СИСТЕМА ВЫДАЧИ</b>\n"
        f"{DIVIDER}\n"
        f"Инструментарий для оперативной отгрузки eSIM покупателям.\n\n"
        f"<i>Выберите оператора для начала процесса:</i>"
    )
    
    # ui.display сам поймет, группа это или ЛС, и сохранит позицию
    await ui.display(event=event, text=text, reply_markup=await get_qr_delivery_main_kb())
    if isinstance(event, CallbackQuery):
        await event.answer()

@router.callback_query(QRDeliveryCD.filter(F.action == "op_list"))
async def cb_delivery_op_list(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Список операторов с доступным стоком."""
    sub_svc = SubmissionService(session=session)
    stats = await sub_svc.get_warehouse_stats_grouped()
    
    if not stats:
        return await callback.answer("📭 Склад пуст.", show_alert=True)

    text = (
        f"❖ <b>ВЫБОР ОПЕРАТОРА</b>\n"
        f"{DIVIDER}\n"
        f"Ниже список категорий, в которых есть готовые к выдаче eSIM (PENDING)."
    )
    
    await ui.display(event=callback, text=text, reply_markup=await get_qr_delivery_operators_kb(stats))
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
                f"👤 <b>АГЕНТ:</b> @{item.owner.username or 'id' + str(item.owner.telegram_id)}"
            )
            # Отправляем в тот же топик, где работаем
            thread_id = message.message_thread_id
            if item.media_type == "photo":
                await bot.send_photo(message.chat.id, item.tg_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            else:
                await bot.send_document(message.chat.id, item.tg_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            
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
        reply_markup=await get_qr_delivery_main_kb()
    )

@router.callback_query(QRDeliveryCD.filter(F.action == "cancel"))
async def cb_delivery_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession, ui: MessageManager):
    await state.clear()
    await cmd_qr_delivery_menu(callback, session, state, ui)
