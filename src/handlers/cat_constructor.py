from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.category_service import CategoryService
from src.services.admin_service import AdminService
from src.states.admin_state import CatConstructorState
from src.keyboards.factory import CatConCD, NavCD
from src.keyboards.builders import get_catcon_main_kb, get_catcon_options_kb, get_catcon_confirm_kb
from src.utils.ui_builder import GDPXRenderer
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="cat-constructor-router")
logger = logging.getLogger(__name__)
_r = GDPXRenderer()

# Пресеты
OPERATORS = ["МТС", "Билайн", "МегаФон", "Теле2", "Йота"]
SIM_TYPES = ["Салон", "ГК", "Корпоративные", "Дилерские", "Другое"]

@router.message(Command("adm_cat"))
async def cmd_adm_cat(message: Message, session: AsyncSession) -> None:
    """Точка входа в конструктор."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    
    text = "<b>Конфигурация кластеров сети</b>\n\nВыберите действие:"
    await message.answer(text, reply_markup=get_catcon_main_kb(), parse_mode="HTML")

@router.callback_query(CatConCD.filter(F.action == "start"))
async def start_creation(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 1: Выбор оператора."""
    await state.set_state(CatConstructorState.step_operator)
    text = _r.render_cat_constructor_step(1, 4, "ОПЕРАТОР", "Выберите оператора из списка:")
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_options_kb(OPERATORS,
     "op"), parse_mode="HTML")
    await callback.answer()

@router.callback_query(CatConCD.filter(F.action == "op"))
async def pick_operator(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Шаг 2: Выбор типа."""
    await state.update_data(operator=callback_data.value)
    await state.set_state(CatConstructorState.step_type)
    text = _r.render_cat_constructor_step(2, 4, "АРХИТЕКТУРА", "Выберите тип сим-карт:")
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_options_kb(SIM_TYPES,
     "type"), parse_mode="HTML")
    await callback.answer()

@router.callback_query(CatConCD.filter(F.action == "type"))
async def pick_type(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Шаг 3: Ввод цены."""
    await state.update_data(sim_type=callback_data.value)
    await state.set_state(CatConstructorState.step_price)
    text = _r.render_cat_constructor_step(3, 4, "ЛИКВИДНОСТЬ", "Введите ставку выкупа (USDT) ответным сообщением:")
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_options_kb([],
     "cancel"), parse_mode="HTML")

    await callback.answer()

@router.message(CatConstructorState.step_price)
async def process_price(message: Message, state: FSMContext) -> None:
    """Шаг 4: Подтверждение."""
    try:
        price = Decimal(message.text.replace(",", "."))
    except (InvalidOperation, ValueError):
        await message.answer("❌ Ошибка: Введите число (например, 0.5)")
        return

    data = await state.get_data()
    await state.update_data(payout_rate=price)
    
    text = _r.render_cat_constructor_confirm(data['operator'], data['sim_type'], str(price))
    await message.answer(text, reply_markup=get_catcon_confirm_kb(), parse_mode="HTML")

@router.callback_query(CatConCD.filter(F.action == "confirm"))
async def confirm_creation(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Финиш: Сохранение категории."""
    data = await state.get_data()
    title = f"{data['operator']} | {data['sim_type']}"
    
    await CategoryService(session=session).create_category(
        title=title,
        operator=data['operator'],
        sim_type=data['sim_type'],
        payout_rate=data['payout_rate'],
        is_active=True
    )
    await session.commit()
    await state.clear()
    
    await callback.message.answer("✅ <b>Кластер успешно активирован!</b>", parse_mode="HTML")
    await callback.message.delete()
    await callback.answer()

@router.callback_query(CatConCD.filter(F.action == "cancel"))
async def cancel_catcon(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена конструктора."""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Конфигурация отменена.")
    await callback.answer()


@router.callback_query(CatConCD.filter(F.action == "list"))
async def catcon_list_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список всех категорий (кластеров) для админа."""

    categories = await CategoryService(session=session).get_all_categories()
    if not categories:
        await callback.answer("🔴 База кластеров пуста", show_alert=True)
        return

    text = "<b>Список всех кластеров сети:</b>\n\n"
    for cat in categories:
        status = "🟢 АКТИВЕН" if cat.is_active else "🔴 ОТКЛЮЧЕН"
        text += f"{status}\n└ <b>ID:</b> <code>{cat.id}</code> | <b>{cat.title}</b> | {cat.payout_rate} USDT\n\n"

    await callback.message.answer(text[:4000], parse_mode="HTML")
    await callback.answer()