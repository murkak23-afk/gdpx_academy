from __future__ import annotations
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.moderation_service import ModerationService
from src.database.models.enums import SubmissionStatus
from src.states.moderation import ModerationStates
from src.callbacks.moderation import AdminBatchCD
from src.keyboards.moderation import (
    get_batch_list_kb,
    get_batch_status_kb,
    get_batch_reasons_kb
)
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.services.admin_service import AdminService


router = Router(name="moderation-batch-router")


@router.callback_query(F.data == "mod_batch_my")
async def start_batch_my(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Вход в Batch-мастер для МОИХ активов (В работе)."""
    await state.update_data(batch_mode="my_work", batch_selected=[])
    # Делегируем отрисовку основному методу
    await start_batch_mode(callback, AdminBatchCD(action="start", val="0"), session, state)


@router.callback_query(AdminBatchCD.filter(F.action == "start"))
async def start_batch_mode(callback: CallbackQuery, callback_data: AdminBatchCD, session: AsyncSession, state: FSMContext):
    """Открытие списка галочек для Batch-мастера."""
    # Если val='my' или '0', обрабатываем это
    val = callback_data.val or "0"
    
    if val == "my":
        await state.update_data(batch_mode="my_work", batch_selected=[])
        page = 0
    else:
        try:
            page = int(val)
        except ValueError:
            page = 0
            
    await state.set_state(ModerationStates.batch_processing)

    data = await state.get_data()
    selected_ids = set(data.get("batch_selected", []))
    batch_mode = data.get("batch_mode", "pending")
    
    # Если мы пришли по кнопке "BATCH-МАСТЕР (ОЧЕРЕДЬ)", сбрасываем режим
    if callback.data == AdminBatchCD(action="start").pack():
        batch_mode = "pending"
        await state.update_data(batch_mode="pending", batch_selected=[])
        selected_ids = set()

    mod_svc = ModerationService(session=session)
    
    if batch_mode == "my_work":
        from src.services.user_service import UserService
        admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        items, total = await mod_svc.get_my_active_paginated(admin.id, page, 10)
        mode_text = "ВАШИ АКТИВЫ (В РАБОТЕ)"
    else:
        items, total = await mod_svc.get_pending_paginated(page, 10)
        mode_text = "ОБЩАЯ ОЧЕРЕДЬ (PENDING)"

    text = (
        f"❖ <b>GDPX // МАССОВЫЕ ДЕЙСТВИЯ</b>\n{DIVIDER}\n"
        f"<i>Выделите активы, чтобы применить к ним массовое действие.</i>\n\n"
        f"🗂 <b>Режим:</b> {mode_text}\n"
        f"📦 <b>Доступно:</b> {total} шт.\n"
        f"🎯 <b>Выделено:</b> {len(selected_ids)} шт.\n"
    )

    current_page_ids = [i.id for i in items]
    await state.update_data(batch_page_ids=current_page_ids, batch_page=page)

    await callback.message.edit_text(
        text,
        reply_markup=get_batch_list_kb(items, selected_ids, page, total),
        parse_mode="HTML"
    )



@router.callback_query(AdminBatchCD.filter(F.action == "toggle"))
async def toggle_batch_item(callback: CallbackQuery, callback_data: AdminBatchCD, state: FSMContext, session: AsyncSession):
    """Ставит / снимает галочку с актива."""
    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    item_id = int(callback_data.val)

    if item_id in selected:
        selected.remove(item_id)
    else:
        selected.add(item_id)

    await state.update_data(batch_selected=list(selected))

    # Перерисовываем текущую страницу
    cb_data = AdminBatchCD(action="start", val=str(data.get("batch_page", 0)))
    await start_batch_mode(callback, cb_data, session, state)


@router.callback_query(AdminBatchCD.filter(F.action == "select_all"))
async def select_all_page(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выделяет все карточки на текущей странице."""
    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    page_ids = data.get("batch_page_ids", [])

    selected.update(page_ids)
    await state.update_data(batch_selected=list(selected))

    cb_data = AdminBatchCD(action="start", val=str(data.get("batch_page", 0)))
    await start_batch_mode(callback, cb_data, session, state)


@router.callback_query(AdminBatchCD.filter(F.action == "clear"))
async def clear_selection(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Сбрасывает все выделенные галочки."""
    await state.update_data(batch_selected=[])

    data = await state.get_data()
    cb_data = AdminBatchCD(action="start", val=str(data.get("batch_page", 0)))
    await start_batch_mode(callback, cb_data, session, state)


@router.callback_query(AdminBatchCD.filter(F.action == "apply"))
async def apply_batch_action(callback: CallbackQuery, state: FSMContext):
    """Переход к выбору статуса для выделенных активов."""
    data = await state.get_data()
    selected = data.get("batch_selected", [])
    if not selected:
        return await callback.answer("Ничего не выбрано!", show_alert=True)

    await state.set_state(ModerationStates.batch_status_select)
    text = (
        f"❖ <b>МАССОВОЕ ДЕЙСТВИЕ</b>\n{DIVIDER}\n"
        f"Вы выбрали <b>{len(selected)}</b> активов.\n"
        f"Какое решение применить ко всей пачке?"
    )
    await callback.message.edit_text(text, reply_markup=get_batch_status_kb(), parse_mode="HTML")


@router.callback_query(AdminBatchCD.filter(F.action == "status"))
async def process_batch_status(callback: CallbackQuery, callback_data: AdminBatchCD, state: FSMContext, session: AsyncSession, bot: Bot):
    """Обработка выбора статуса."""
    status_type = callback_data.val

    if status_type == "accepted":
        await _finalize_batch_job(callback, state, session, bot, SubmissionStatus.ACCEPTED)
    else:
        await state.set_state(ModerationStates.batch_reason_select)
        await callback.message.edit_reply_markup(reply_markup=get_batch_reasons_kb(status_type))


@router.callback_query(AdminBatchCD.filter(F.action == "reason"))
async def process_batch_reason(callback: CallbackQuery, callback_data: AdminBatchCD, state: FSMContext, session: AsyncSession, bot: Bot):
    """Обработка выбора готовой причины."""
    type_key, reason = callback_data.val.split(":", 1)
    status_map = {
        "not_scan": SubmissionStatus.NOT_A_SCAN,
        "reject": SubmissionStatus.REJECTED,
        "block": SubmissionStatus.BLOCKED
    }
    await _finalize_batch_job(callback, state, session, bot, status_map[type_key], reason=reason)


@router.callback_query(AdminBatchCD.filter(F.action == "custom"))
async def start_batch_custom_comment(callback: CallbackQuery, callback_data: AdminBatchCD, state: FSMContext):
    """Переход в режим ввода своего комментария для пачки."""
    await state.update_data(batch_defect_mode=callback_data.val)
    await state.set_state(ModerationStates.batch_custom_comment)
    await callback.message.answer(
        "✍️ <b>Введите ОБЩИЙ комментарий для всей выделенной пачки:</b>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ModerationStates.batch_custom_comment, F.text)
async def process_batch_custom_comment(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Обработка введённого кастомного комментария."""
    data = await state.get_data()
    mode = data.get("batch_defect_mode", "reject")
    status_map = {
        "not_scan": SubmissionStatus.NOT_A_SCAN,
        "reject": SubmissionStatus.REJECTED,
        "block": SubmissionStatus.BLOCKED
    }
    await _finalize_batch_job(message, state, session, bot, status_map[mode], reason="Другое", comment=message.text)


async def _finalize_batch_job(
    message_obj: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    status: SubmissionStatus,
    reason: str = None,
    comment: str = None
):
    """Ядро массовой финализации."""
    data = await state.get_data()
    selected_ids = data.get("batch_selected", [])

    from src.services.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(message_obj.from_user.id)

    mod_svc = ModerationService(session=session)
    count = await mod_svc.bulk_finalize_submissions(selected_ids, status, admin.id, reason, comment)
    await session.commit()

    # Очищаем выбор
    await state.update_data(batch_selected=[])

    msg_text = f"✅ <b>ГОТОВО!</b> Успешно обработано <b>{count}</b> карточек."

    if isinstance(message_obj, Message):
        await message_obj.answer(msg_text, parse_mode="HTML")
    else:
        await message_obj.message.edit_text(msg_text, parse_mode="HTML")
        await message_obj.answer("Операция завершена")