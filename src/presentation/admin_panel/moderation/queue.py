from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.factory import AdminQueueCD, AdminSellerQueueCD
from src.database.models.enums import SubmissionStatus
from src.database.models.user import User
from .keyboards import get_seller_workspace_kb, get_sellers_queue_kb
from src.domain.moderation.moderation_service import ModerationService
from src.domain.users.user_service import UserService
from src.domain.submission.workflow_service import WorkflowService
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.ui_builder import DIVIDER

router = Router(name="moderation-queue-router")


@router.callback_query(AdminQueueCD.filter(F.action == "start"))
@router.callback_query(AdminSellerQueueCD.filter(F.action == "list"))
@router.callback_query(F.data.startswith("mod_q:refresh"))
async def on_moderation_queue(callback: CallbackQuery, session: AsyncSession, state: FSMContext, callback_data: AdminQueueCD | AdminSellerQueueCD | None = None):
    """Уровень 1: Список продавцов (Склад, Выданные, Проверка)."""
    await state.clear() 

    # Определяем статус
    status_str = "pending"
    if isinstance(callback_data, AdminSellerQueueCD):
        status_str = callback_data.status
    elif isinstance(callback_data, AdminQueueCD):
        status_str = "pending"
    elif callback.data.startswith("mod_q:refresh:"):
        status_str = callback.data.split(":")[-1]
    
    status_map = {
        "pending": [SubmissionStatus.PENDING],
        "in_work": [SubmissionStatus.IN_WORK],
        "verification": [SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]
    }
    status_list = status_map.get(status_str, [SubmissionStatus.PENDING])
    
    mod_service = ModerationService(session=session)
    sellers_data = await mod_service.get_pending_sellers(status=status_list)

    ui_data = {
        "pending": ("🚀 СКЛАД АКТИВОВ", "Ниже список агентов с новыми заявками."),
        "in_work": ("📟 ВЫДАННЫЕ АКТИВЫ", "Агенты с активами на руках у байеров."),
        "verification": ("✨ ПРОВЕРКА АКТИВОВ", "Активы, ожидающие ручного зачёта (SLA > 1h).")
    }
    title, descr = ui_data.get(status_str, ("ОЧЕРЕДЬ", "Список агентов"))

    if not sellers_data:
        text = f"❖ <b>{title}</b>\n{DIVIDER}\n✨ <b>Все чисто! Активных записей нет.</b>"
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_sellers_queue_kb([], status=status_str), parse_mode="HTML")
        await callback.answer()
        return

    text = (
        f"❖ <b>{title}</b>\n{DIVIDER}\n"
        f"<i>{descr}\nСортировка по SLA.</i>"
    )
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_sellers_queue_kb(sellers_data, status=status_str), parse_mode="HTML")
    await callback.answer()


@router.callback_query(AdminSellerQueueCD.filter(F.action == "view"))
@router.callback_query(AdminSellerQueueCD.filter(F.action == "toggle"))
async def show_seller_detail(callback: CallbackQuery, callback_data: AdminSellerQueueCD, session: AsyncSession, state: FSMContext):
    """Уровень 2: Универсальное рабочее пространство (Выбор + Действия)."""
    
    # 1. Работа с выделением
    data = await state.get_data()
    selected_ids = set(data.get("selected_ids", []))
    
    if callback_data.action == "toggle" and callback_data.val:
        item_id = int(callback_data.val)
        if item_id in selected_ids: selected_ids.remove(item_id)
        else: selected_ids.add(item_id)
        await state.update_data(selected_ids=list(selected_ids))

    # 2. Получение данных
    status_map = {
        "pending": [SubmissionStatus.PENDING],
        "in_work": [SubmissionStatus.IN_WORK],
        "verification": [SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]
    }
    status_list = status_map.get(callback_data.status, [SubmissionStatus.PENDING])

    mod_service = ModerationService(session=session)
    items, total = await mod_service.get_pending_for_seller_paginated(
        callback_data.user_id, status=status_list, page=callback_data.page, page_size=10
    )
    
    if not items and callback_data.page == 0:
        await callback.answer("🔴 Этот раздел уже разобран!", show_alert=True)
        return await on_moderation_queue(callback, session, state, callback_data=callback_data)

    seller = await session.get(User, callback_data.user_id)
    seller_name = f"@{seller.username}" if seller and seller.username else f"ID:{callback_data.user_id}"

    ui_titles = {"pending": "СКЛАД", "in_work": "ВЫДАНО", "verification": "ПРОВЕРКА"}
    title = ui_titles.get(callback_data.status, "АКТИВЫ")

    text = (
        f"❖ <b>{title}: {seller_name}</b>\n"
        f"{DIVIDER}\n"
        f"<i>Выберите активы для массового действия или перейдите в детальный режим.</i>\n\n"
        f"💎 <b>ВСЕГО:</b> <code>{total}</code> шт."
    )

    await edit_message_text_or_caption_safe(
        callback.message,
        text,
        reply_markup=get_seller_workspace_kb(
            items=items, 
            selected_ids=selected_ids, 
            user_id=callback_data.user_id, 
            status=callback_data.status, 
            page=callback_data.page, 
            total=total
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(AdminSellerQueueCD.filter(F.action == "apply"))
async def handle_mass_action(callback: CallbackQuery, callback_data: AdminSellerQueueCD, session: AsyncSession, state: FSMContext, bot: Bot):
    """Применение массовых действий к выбранным айтемам."""
    data = await state.get_data()
    selected_ids = data.get("selected_ids", [])
    
    mod_svc = ModerationService(session=session)
    WorkflowService(session=session)
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)

    if callback_data.val == "clear":
        await state.update_data(selected_ids=[])
        await callback.answer("🧹 Выбор очищен")
        return await show_seller_detail(callback, callback_data, session, state)

    if callback_data.val == "select_all":
        # Выбираем только айтемы текущей страницы (для простоты и безопасности)
        status_map = {"pending": [SubmissionStatus.PENDING], "in_work": [SubmissionStatus.IN_WORK], "verification": [SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]}
        items, _ = await mod_svc.get_pending_for_seller_paginated(callback_data.user_id, status=status_map.get(callback_data.status), page=callback_data.page)
        new_ids = set(selected_ids) | {i.id for i in items}
        await state.update_data(selected_ids=list(new_ids))
        await callback.answer(f"✔️ Выбрано: {len(new_ids)}")
        return await show_seller_detail(callback, callback_data, session, state)

    if callback_data.val == "take_next":
        # Переход в детальный инспектор (берем первый доступный айтем)
        actual_taken = await mod_svc.take_items_to_work(admin.id, 1, user_id=callback_data.user_id)
        if actual_taken > 0:
            from src.presentation.admin_panel.moderation.inspector import _render_next_item
            await callback.message.delete()
            return await _render_next_item(bot, callback.from_user.id, session, state)
        else:
            return await callback.answer("🔴 Нет доступных активов", show_alert=True)

    # Массовые статусы: accept, reject, block
    if not selected_ids:
        return await callback.answer("⚠️ Ничего не выбрано!", show_alert=True)

    await callback.answer(f"⏳ Обработка {len(selected_ids)} шт...")
    
    target_status = {
        "accept": SubmissionStatus.ACCEPTED,
        "reject": SubmissionStatus.REJECTED,
        "block": SubmissionStatus.BLOCKED
    }.get(callback_data.val)

    if target_status:
        count = await mod_svc.bulk_finalize_submissions(
            submission_ids=selected_ids,
            status=target_status,
            admin_id=admin.id,
            bot=bot
        )
        await session.commit()
        await state.update_data(selected_ids=[])
        await callback.answer(f"✅ Успешно обработано: {count} шт.", show_alert=True)
        return await show_seller_detail(callback, callback_data, session, state)

    await callback.answer("❌ Неизвестное действие")


@router.callback_query(AdminSellerQueueCD.filter(F.action == "return_warehouse"))
async def handle_return_warehouse(callback: CallbackQuery, callback_data: AdminSellerQueueCD, session: AsyncSession, state: FSMContext):
    """Массовый возврат активов селлера на склад."""
    status_map = {
        "in_work": [SubmissionStatus.IN_WORK],
        "verification": [SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]
    }
    mod_service = ModerationService(session=session)
    items, total = await mod_service.get_pending_for_seller_paginated(callback_data.user_id, status=status_map.get(callback_data.status), page_size=999)
    
    if not items: return await callback.answer("🔴 Нечего возвращать", show_alert=True)
        
    wf_svc = WorkflowService(session)
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    
    count = 0
    for it in items:
        res = await wf_svc.transition(submission_id=it.id, admin_id=admin.id, to_status=SubmissionStatus.PENDING, comment="Массовый возврат")
        if res: count += 1
        
    await session.commit()
    await callback.answer(f"✅ {count} шт. возвращено на склад", show_alert=True)
    await show_seller_detail(callback, callback_data, session, state)
