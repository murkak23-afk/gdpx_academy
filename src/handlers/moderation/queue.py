from __future__ import annotations
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.fsm.context import FSMContext

from src.services.moderation_service import ModerationService
from src.services.user_service import UserService
from src.callbacks.moderation import AdminQueueCD, AdminSellerQueueCD
from src.keyboards.moderation import get_sellers_queue_kb, get_seller_detail_actions_kb
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT

router = Router(name="moderation-queue-router")

@router.callback_query(AdminQueueCD.filter(F.action == "start"))
@router.callback_query(F.data == "mod_q:refresh")
async def on_moderation_queue(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear() 
    """Уровень 1: Список продавцов с ожидающими активами."""

    mod_service = ModerationService(session=session)
    sellers_data = await mod_service.get_pending_sellers()

    if not sellers_data:
        text = f"❖ <b>ОЧЕРЕДЬ АКТИВОВ</b>\n{DIVIDER}\n✨ <b>Все чисто! Активных заявок нет.</b>"
        await callback.message.edit_text(text, reply_markup=get_sellers_queue_kb([]), parse_mode="HTML")
        return

    text = (
        f"❖ <b>ОЧЕРЕДЬ АКТИВОВ</b>\n{DIVIDER}\n"
        f"<i>Ниже список агентов, ожидающих дефектовку.\nСортировка по времени ожидания (SLA).</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_sellers_queue_kb(sellers_data), parse_mode="HTML")

@router.callback_query(AdminSellerQueueCD.filter(F.action == "view"))
async def show_seller_detail(callback: CallbackQuery, callback_data: AdminSellerQueueCD, session: AsyncSession, state: FSMContext):
    """Уровень 2: Детализация по конкретному продавцу."""
    await state.clear()

    mod_service = ModerationService(session=session)
    items = await mod_service.get_pending_for_seller(callback_data.user_id, limit=100)
    
    if not items:
        await callback.answer("🔴 Очередь продавца уже разобрана!", show_alert=True)
        await on_moderation_queue(callback, session, state)
        return

    # Загружаем селлера напрямую из сессии
    from src.database.models.user import User
    seller = await session.get(User, callback_data.user_id)
    
    # Отказоустойчивая обработка: если селлер удален из БД, но активы остались
    seller_name = "Удаленный агент"
    if seller:
        seller_name = f"@{seller.username}" if seller.username else f"ID:{seller.id}"

    lines = [
        f"❖ <b>АКТИВЫ: {seller_name}</b>\n{DIVIDER}",
        "<i>Инвентарь в очереди:</i>\n"
    ]

    for it in items:
        wait_min = int((datetime.now(timezone.utc) - it.created_at).total_seconds() / 60)
        sla = "🔴" if wait_min > 15 else "🟡" if wait_min > 8 else "🟢"
        phone = it.phone_normalized
        ident = f"...{phone[-4:]}" if phone else f"#{it.id}"
        lines.append(f"{sla} <b>{it.category.title}</b> | <code>{ident}</code> | {it.fixed_payout_rate} USDT")

    actual_count = len(await mod_service.get_pending_for_seller(callback_data.user_id, limit=999))

    lines.append(f"\n{DIVIDER_LIGHT}\nВсего у продавца: <b>{actual_count} шт.</b>")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=get_seller_detail_actions_kb(callback_data.user_id, actual_count),
        parse_mode="HTML"
    )