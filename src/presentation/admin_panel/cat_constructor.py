"""Управление категориями (кластерами) сети. Создание и просмотр."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation import (
    get_cat_manage_confirm_delete_kb,
    get_cat_manage_detail_kb,
    get_cat_manage_list_kb,
    get_catcon_confirm_kb,
    get_catcon_main_kb,
    get_catcon_options_kb,
)
from src.presentation.common.factory import CatConCD, CatManageCD
from src.domain.moderation.admin_service import AdminService
from src.domain.submission.category_service import CategoryService
from src.domain.moderation.admin_state import CatConstructorState
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.ui_builder import GDPXRenderer

router = Router(name="cat-constructor-router")
logger = logging.getLogger(__name__)
_r = GDPXRenderer()

# Базовые пресеты
OPERATORS = ["МТС", "Билайн", "МегаФон", "Теле2", "Йота"]
SIM_TYPES = ["Салон", "ГК", "Корпоративные", "Дилерские", "Другое"]


@router.message(Command("adm_cat"))
async def cmd_adm_cat(message: Message, session: AsyncSession) -> None:
    """Точка входа в конструктор (только для админа)."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    text = "<b>Конфигурация кластеров сети</b>\n\nВыберите действие:"
    await message.answer(text, reply_markup=await get_catcon_main_kb(), parse_mode="HTML")

@router.callback_query(CatConCD.filter(F.action == "start"))
async def start_creation(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 1: Выбор оператора."""
    await state.set_state(CatConstructorState.step_operator)
    text = _r.render_cat_constructor_step(1, 4, "ОПЕРАТОР", "Выберите оператора из списка или введите свой вариант текстом:")

    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_catcon_options_kb(OPERATORS, "op"), parse_mode="HTML"
    )
    await callback.answer()

# --- ЛОГИКА ОПЕРАТОРА ---

@router.callback_query(CatConCD.filter(F.action == "custom_op"), StateFilter(CatConstructorState.step_operator))
async def ask_custom_operator(callback: CallbackQuery) -> None:
    """Запрос ручного ввода оператора."""
    text = _r.render_cat_constructor_step(1, 4, "СВОЙ ОПЕРАТОР", "Введите название оператора ответным сообщением:")
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_options_kb([], "cancel"), parse_mode="HTML")
    await callback.answer()

@router.message(StateFilter(CatConstructorState.step_operator), F.text)
async def process_custom_operator(message: Message, state: FSMContext) -> None:
    """Прием ручного ввода оператора."""
    val = message.text.strip()
    if len(val) < 2:
        return await message.answer("❌ Слишком короткое название. Попробуйте еще раз:")
    
    await state.update_data(operator=val)
    await show_step_type(message, state)

@router.callback_query(CatConCD.filter(F.action == "op"), StateFilter(CatConstructorState.step_operator))
async def pick_operator(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Выбор оператора из списка."""
    await state.update_data(operator=callback_data.value)
    await show_step_type(callback, state)
    await callback.answer()

# --- ЛОГИКА ТИПА ---

async def show_step_type(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Переход к шагу выбора типа."""
    await state.set_state(CatConstructorState.step_type)
    text = _r.render_cat_constructor_step(2, 4, "АРХИТЕКТУРА", "Выберите тип сим-карт или введите свой вариант текстом:")
    
    kb = get_catcon_options_kb(SIM_TYPES, "type")
    
    if isinstance(event, CallbackQuery):
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(CatConCD.filter(F.action == "custom_type"), StateFilter(CatConstructorState.step_type))
async def ask_custom_type(callback: CallbackQuery) -> None:
    """Запрос ручного ввода типа."""
    text = _r.render_cat_constructor_step(2, 4, "СВОЯ АРХИТЕКТУРА", "Введите тип сим-карт ответным сообщением (например: Дилерские V2):")
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_options_kb([], "cancel"), parse_mode="HTML")
    await callback.answer()

@router.message(StateFilter(CatConstructorState.step_type), F.text)
async def process_custom_type(message: Message, state: FSMContext) -> None:
    """Прием ручного ввода типа."""
    val = message.text.strip()
    if len(val) < 2:
        return await message.answer("❌ Слишком короткое название. Попробуйте еще раз:")
    
    await state.update_data(sim_type=val)
    await show_step_price(message, state)

@router.callback_query(CatConCD.filter(F.action == "type"), StateFilter(CatConstructorState.step_type))
async def pick_type(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Выбор типа из списка."""
    await state.update_data(sim_type=callback_data.value)
    await show_step_price(callback, state)
    await callback.answer()

# --- ЛОГИКА ЦЕНЫ ---

async def show_step_price(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Переход к вводу цены."""
    await state.set_state(CatConstructorState.step_price)
    text = _r.render_cat_constructor_step(
        3, 4, "ЛИКВИДНОСТЬ", "Введите фиксированную ставку выкупа (USDT) ответным сообщением (например 1.5):"
    )
    kb = get_catcon_options_kb([], "cancel")
    
    if isinstance(event, CallbackQuery):
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(StateFilter(CatConstructorState.step_price))
async def process_price(message: Message, state: FSMContext) -> None:
    """Шаг 4: Валидация цены и подтверждение."""
    if not message.text:
        return

    try:
        price_val = message.text.replace(",", ".").strip()
        price = Decimal(price_val)
        if price <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer("❌ <b>Ошибка:</b> Введите корректное положительное число (например 1.5)", parse_mode="HTML")
        return

    data = await state.get_data()
    operator = data.get("operator", "Unknown")
    sim_type = data.get("sim_type", "Unknown")

    await state.update_data(payout_rate=str(price))
    await state.set_state(CatConstructorState.step_confirm)

    text = _r.render_cat_constructor_confirm(operator, sim_type, str(price))
    await message.answer(text, reply_markup=get_catcon_confirm_kb(), parse_mode="HTML")


@router.callback_query(CatConCD.filter(F.action == "confirm"), StateFilter(CatConstructorState.step_confirm))
async def confirm_creation(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Финальное сохранение категории."""
    data = await state.get_data()
    operator = data.get("operator")
    sim_type = data.get("sim_type")
    payout_rate_str = data.get("payout_rate")

    if not operator or not sim_type or not payout_rate_str:
        await callback.answer("🔴 Ошибка: данные утеряны. Начните заново.", show_alert=True)
        await state.clear()
        return

    payout_rate = Decimal(payout_rate_str)
    title = f"{operator} | {sim_type}"

    try:
        category = await CategoryService(session=session).create_category(
            title=title,
            operator=operator,
            sim_type=sim_type,
            payout_rate=payout_rate,
            is_active=True,
        )
        await session.commit()

        await state.clear()

        success_text = (
            f"✅ <b>Кластер [ID: {category.id}] успешно активирован!</b>\n"
            f"└ Ставка: <code>{payout_rate}</code> USDT\n\n"
            f"Теперь доступен агентам для загрузки eSIM."
        )
        await callback.message.answer(success_text, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logger.error("Error creating category: %s", e, exc_info=True)
        await callback.answer("🔴 Системная ошибка при сохранении", show_alert=True)

@router.callback_query(CatConCD.filter(F.action == "list"))
async def catcon_list_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    """Премиум-список всех категорий для админа."""
    categories = await CategoryService(session=session).get_all_categories()
    if not categories:
        await callback.answer("🔴 База кластеров пуста", show_alert=True)
        return

    text = "<b>Управление кластерами сети:</b>\n\nВыберите кластер для настройки:"
    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_cat_manage_list_kb(categories), parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(CatManageCD.filter(F.action == "view"))
async def view_category(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession, state: FSMContext) -> None:
    """Отображение детальной карточки управления кластером."""
    await state.clear()
    cat = await CategoryService(session=session).get_by_id(callback_data.cat_id)
    if not cat:
        await callback.answer("🔴 Кластер не найден", show_alert=True)
        return

    text = _r.render_category_manage(cat)
    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_cat_manage_detail_kb(cat), parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(CatManageCD.filter(F.action == "toggle_active"))
async def cat_manage_toggle_active(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession) -> None:
    """Включение / отключение кластера."""
    cat = await CategoryService(session=session).get_by_id(callback_data.cat_id)
    if not cat: return
         
    await CategoryService(session=session).set_active(cat.id, not cat.is_active)
    await session.commit()

    cat = await CategoryService(session=session).get_by_id(callback_data.cat_id)
    text = _r.render_category_manage(cat)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_cat_manage_detail_kb(cat),
parse_mode="HTML")
    await callback.answer(f"Статус: {'АКТИВЕН' if cat.is_active else 'ОТКЛЮЧЕН'}")

@router.callback_query(CatManageCD.filter(F.action == "toggle_priority"))
async def cat_manage_toggle_priority(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession) -> None:
    """Изменение приоритета кластера (🏮) с СМС в общий чат."""
    cat = await CategoryService(session=session).get_by_id(callback_data.cat_id)
    if not cat: return

    new_prio = not getattr(cat, "is_priority", False)
    await CategoryService(session=session).set_priority(cat.id, new_prio)
    await session.commit()
 
    cat = await CategoryService(session=session).get_by_id(callback_data.cat_id)
    text = _r.render_category_manage(cat)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_cat_manage_detail_kb(cat),
parse_mode="HTML")
    await callback.answer("Приоритет изменен")

    # Если включили приоритет — кидаем СМС в общий чат модерации/ворка
    if new_prio:
        from src.core.config import get_settings
        chat_id = get_settings().moderation_chat_id
        if chat_id:
            try:
                alert_text = (
                    f"🚨 <b>ВНИМАНИЕ! ГОРЯЩИЙ ЗАПРОС!</b>\n"
                    f"▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                    f"Срочно нужен материал:\n"
                    f"📦 <b>{cat.title}</b>\n"
                    f"💰 Ставка выкупа: <b>{cat.payout_rate} USDT</b>\n\n"
                    f"<i>Агенты, ждем загрузок!</i>"
                )
                await callback.bot.send_message(chat_id=chat_id, text=alert_text, parse_mode="HTML")
            except Exception:
                pass


@router.callback_query(CatManageCD.filter(F.action == "confirm_delete"))
async def cat_manage_confirm_delete(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession) -> None:
    """Предупреждение перед удалением."""
    text = "⚠️ <b>ВНИМАНИЕ! КРИТИЧЕСКОЕ ДЕЙСТВИЕ</b>\n\nВы собираетесь безвозвратно удалить этот кластер.\n<i>(Если по нему есть история загрузок, он будет скрыт и отключен, но не удален полностью).</i>\n\nВы уверены?"
    await edit_message_text_or_caption_safe(callback.message, text,
       reply_markup=get_cat_manage_confirm_delete_kb(callback_data.cat_id), parse_mode="HTML")
    await callback.answer()

@router.callback_query(CatManageCD.filter(F.action == "delete"))
async def cat_manage_delete(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession) -> None:
    """Финальное удаление кластера."""
    res = await CategoryService(session=session).delete_category(callback_data.cat_id)
    await session.commit()

    if res == "deleted":
        await callback.answer("🗑 Кластер удален", show_alert=True)
    elif res == "deactivated":
        await callback.answer("⚠️ По кластеру есть история заявок. Он отключен (is_active=False)",
       show_alert=True)
        
    await catcon_list_categories(callback, session)
    

@router.callback_query(CatManageCD.filter(F.action == "edit_price"))
async def cat_manage_edit_price(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession,
       state: FSMContext) -> None:
    """Запуск FSM изменения цены существующего кластера."""
    await state.update_data(edit_cat_id=callback_data.cat_id)
    await state.set_state(CatConstructorState.edit_price)
    
    text = "💰 <b>ИЗМЕНЕНИЕ СТАВКИ ВЫКУПА</b>\n\n⚠️ <i>Внимание: изменение ставки затронет все новые загрузки. На старые, уже загруженные eSIM, это не повлияет.</i>\n\nВведите новую ставку (USDT) ответным сообщением:"
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена",
       callback_data=CatManageCD(action="view", cat_id=callback_data.cat_id).pack())]])
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=cancel_kb, parse_mode="HTML")
    await callback.answer()
    

@router.message(StateFilter(CatConstructorState.edit_price))
async def process_edit_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Прием новой цены и сохранение в БД."""
    if not message.text: return
    try:
       from decimal import Decimal
       price = Decimal(message.text.replace(",", ".").strip())
       if price <= 0: raise ValueError("Price > 0")
    except Exception:
        await message.answer("❌ Ошибка: Введите число > 0 (например, 1.5)", parse_mode="HTML")
        return
     
    data = await state.get_data()
    cat_id = data.get("edit_cat_id")
    if not cat_id:
        await state.clear()
        return
     
    await CategoryService(session=session).update_payout_rate(cat_id, price)
    await session.commit()
    await state.clear()
     
    cat = await CategoryService(session=session).get_by_id(cat_id)
    text = _r.render_category_manage(cat)
    
    success_msg = "✅ <b>Ставка успешно изменена!</b>\n\n" + text
    await message.answer(success_msg, reply_markup=get_cat_manage_detail_kb(cat), parse_mode="HTML")

@router.callback_query(CatConCD.filter(F.action == "cancel"))
async def cancel_catcon(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Отмена на любом шаге: возврат в меню управления."""
    await state.clear()
    text = "❌ <b>Конфигурация кластера отменена.</b>\n\nВыберите действие:"
    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=await get_catcon_main_kb(), parse_mode="HTML"
    )
    await callback.answer()
