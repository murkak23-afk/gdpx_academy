from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.factory import AdminGradeCD, AdminSearchCD
from src.presentation.admin_panel.moderation.inspector import _render_next_item
from .keyboards import get_search_filters_kb, get_search_results_kb
from src.domain.moderation.moderation_service import ModerationService
from src.domain.moderation.moderation_state import ModerationStates
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT

router = Router(name="moderation-search-router")


@router.callback_query(F.data == "mod_search")
async def start_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ModerationStates.search_query)
    text = (
        f"❖ <b>ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК</b>\n{DIVIDER}\n"
        f"Введите запрос ответным сообщением.\n\n"
        f"<b>Поддерживаемые форматы:</b>\n"
        f" ├ <code>5678</code> (последние цифры номера)\n"
        f" ├ <code>7938...</code> (полный номер)\n"
        f" ├ <code>12345</code> (ID актива или селлера)\n"
        f" └ <code>@username</code> (никнейм селлера)\n"
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ ОТМЕНА", callback_data="mod_back_dash")]])
    await callback.message.edit_text(text, reply_markup=cancel_kb, parse_mode="HTML")


@router.message(ModerationStates.search_query, F.text)
async def process_search_query(message: Message, state: FSMContext, session: AsyncSession):
    query = message.text.strip()
    await state.update_data(mod_last_query=query)
    try:
        await message.delete()
    except Exception:
        pass
    await _execute_and_show_search(message, session, query, "all")


@router.callback_query(AdminSearchCD.filter(F.action == "filter"))
async def apply_search_filter(callback: CallbackQuery, callback_data: AdminSearchCD, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    query = data.get("mod_last_query", callback_data.query)
    await _execute_and_show_search(callback.message, session, query, callback_data.filter_type)
    await callback.answer()


async def _execute_and_show_search(message_obj: Message | CallbackQuery, session: AsyncSession, query: str, filter_type: str):
    mod_svc = ModerationService(session=session)
    items = await mod_svc.search_pending_assets(query, filter_type, limit=20)

    text = (
        f"❖ <b>РЕЗУЛЬТАТЫ ПОИСКА</b>\n{DIVIDER}\n"
        f"🔍 <b>Запрос:</b> <code>{escape(query)}</code>\n"
        f"🗂 <b>Найдено:</b> {len(items)} шт. (показаны первые 20)\n"
        f"{DIVIDER_LIGHT}\n"
    )

    if not items:
        text += "<i>По вашему запросу ничего не найдено в очереди PENDING.</i>"
    else:
        text += "<i>Нажмите на актив, чтобы мгновенно забрать его в Инспектор:</i>"

    kb = get_search_results_kb(items, query, filter_type)
    filters_kb = get_search_filters_kb(query, filter_type)
    kb.inline_keyboard = filters_kb.inline_keyboard + kb.inline_keyboard

    if isinstance(message_obj, Message):
        await message_obj.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_obj.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminSearchCD.filter(F.action == "take_all"))
async def search_take_all(callback: CallbackQuery, callback_data: AdminSearchCD, session: AsyncSession, state: FSMContext, bot: Bot):
    data = await state.get_data()
    query = data.get("mod_last_query", callback_data.query)
    mod_svc = ModerationService(session=session)

    items = await mod_svc.search_pending_assets(query, callback_data.filter_type, limit=50)
    if not items:
        return await callback.answer("🔴 Активы уже разобраны!", show_alert=True)

    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)

    taken = await mod_svc.take_specific_items_to_work(admin.id, [i.id for i in items])
    await session.commit()

    await callback.answer(f"✅ Взято в работу: {taken} шт.", show_alert=True)
    await callback.message.delete()
    await _render_next_item(bot, callback.from_user.id, session, state)


@router.callback_query(AdminGradeCD.filter(F.action == "take"))
async def search_take_single(callback: CallbackQuery, callback_data: AdminGradeCD, session: AsyncSession, state: FSMContext, bot: Bot):
    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    mod_svc = ModerationService(session=session)

    taken = await mod_svc.take_specific_items_to_work(admin.id, [callback_data.item_id])
    await session.commit()

    if taken:
        await callback.message.delete()
        await _render_next_item(bot, callback.from_user.id, session, state)
    else:
        await callback.answer("🔴 Актив уже взят другим модератором", show_alert=True)