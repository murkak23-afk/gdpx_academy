"""Управление категориями (кластерами) сети. Создание и просмотр."""

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
from src.keyboards.factory import CatConCD
from src.keyboards.builders import get_catcon_main_kb, get_catcon_options_kb, get_catcon_confirm_kb
from src.utils.ui_builder import GDPXRenderer
from src.utils.text_format import edit_message_text_or_caption_safe

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
    await message.answer(text, reply_markup=get_catcon_main_kb(), parse_mode="HTML")


@router.callback_query(CatConCD.filter(F.action == "list"))
async def catcon_list_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список всех категорий для админа."""
    categories = await CategoryService(session=session).get_all_categories()
    if not categories:
        await callback.answer("🔴 База кластеров пуста", show_alert=True)
        return

    text = "<b>Список всех кластеров сети:</b>\n\n"
    for cat in categories:
        status = "🟢 АКТИВЕН" if cat.is_active else "🔴 ОТКЛЮЧЕН"
        text += f"{status}\n└ <b>ID:</b> <code>{cat.id}</code> | <b>{cat.title}</b> | <code>{cat.payout_rate}</code> USDT\n\n"

    await callback.message.answer(text[:4000], parse_mode="HTML")
    await callback.answer()


@router.callback_query(CatConCD.filter(F.action == "start"))
async def start_creation(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 1: Выбор оператора."""
    await state.set_state(CatConstructorState.step_operator)
    text = _r.render_cat_constructor_step(1, 4, "ОПЕРАТОР", "Выберите оператора из списка:")

    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_catcon_options_kb(OPERATORS, "op"), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(CatConCD.filter(F.action == "op"), StateFilter(CatConstructorState.step_operator))
async def pick_operator(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Шаг 2: Выбор типа."""
    await state.update_data(operator=callback_data.value)
    await state.set_state(CatConstructorState.step_type)

    text = _r.render_cat_constructor_step(2, 4, "АРХИТЕКТУРА", "Выберите тип сим-карт:")
    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_catcon_options_kb(SIM_TYPES, "type"), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(CatConCD.filter(F.action == "type"), StateFilter(CatConstructorState.step_type))
async def pick_type(callback: CallbackQuery, callback_data: CatConCD, state: FSMContext) -> None:
    """Шаг 3: Ввод цены."""
    await state.update_data(sim_type=callback_data.value)
    await state.set_state(CatConstructorState.step_price)

    text = _r.render_cat_constructor_step(
        3, 4, "ЛИКВИДНОСТЬ", "Введите фиксированную ставку выкупа (USDT) ответным сообщением (например 1.5):"
    )
    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_catcon_options_kb([], "cancel"), parse_mode="HTML"
    )
    await callback.answer()


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


@router.callback_query(CatConCD.filter(F.action == "cancel"))
async def cancel_catcon(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена на любом шаге."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("❌ <b>Конфигурация кластера отменена.</b>", parse_mode="HTML")
    await callback.answer()