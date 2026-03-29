"""Конструктор категорий (/adm_cat) — пошаговый SPA-инлайн для Chief Admin.

Шаги создания: Оператор → Тип → Цена → Подтверждение.
Результат: категория «Оператор | Тип» с ценой в USDT.

Также: просмотр деталей, редактирование (оператор/тип/цена), удаление, вкл/выкл.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.callbacks import (
    CB_CATCON_CANCEL,
    CB_CATCON_CONFIRM,
    CB_CATCON_DELETE,
    CB_CATCON_DELETE_YES,
    CB_CATCON_FORCE_DELETE_YES,
    CB_CATCON_DETAIL,
    CB_CATCON_EDIT,
    CB_CATCON_HOLD,
    CB_CATCON_LIST,
    CB_CATCON_OPERATOR,
    CB_CATCON_TOGGLE,
    CB_CATCON_TYPE,
)
from src.services import AdminService, CategoryService
from src.states.admin_state import CatConstructorState
from src.utils.text_format import edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

router = Router(name="cat-constructor-router")
_r = GDPXRenderer()

# ─── Пресеты ────────────────────────────────────────────────────
OPERATORS = ["МТС", "Билайн", "МегаФон", "Теле2", "Йота"]
SIM_TYPES = ["Салон", "ГК", "Корпоративные", "Дилерские", "Другое"]
HOLD_OPTIONS = ["Безхолд", "15 мин", "30 мин", "1 час", "3 часа", "Другое"]


# ─── Клавиатуры ─────────────────────────────────────────────────

def _operator_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=op, callback_data=f"{CB_CATCON_OPERATOR}:{op}")]
        for op in OPERATORS
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CATCON_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _type_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t, callback_data=f"{CB_CATCON_TYPE}:{t}")]
        for t in SIM_TYPES
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CATCON_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hold_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=h, callback_data=f"{CB_CATCON_HOLD}:{h}")]
        for h in HOLD_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CATCON_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data=CB_CATCON_CONFIRM)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CATCON_CANCEL)],
        ]
    )


def _catcon_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать категорию", callback_data=f"{CB_CATCON_OPERATOR}:_start")],
            [InlineKeyboardButton(text="📋 Список категорий", callback_data=CB_CATCON_LIST)],
        ]
    )


def _cat_list_keyboard(categories: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in categories[:20]:
        state = "✅" if c.is_active else "⛔"
        rows.append([
            InlineKeyboardButton(
                text=f"{state} {c.title} · {c.payout_rate} USDT",
                callback_data=f"{CB_CATCON_DETAIL}:{c.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="➕ Создать категорию", callback_data=f"{CB_CATCON_OPERATOR}:_start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cat_detail_keyboard(cat_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "⛔ Выключить" if is_active else "✅ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Оператор", callback_data=f"{CB_CATCON_EDIT}:{cat_id}:operator"),
                InlineKeyboardButton(text="📂 Тип", callback_data=f"{CB_CATCON_EDIT}:{cat_id}:type"),
            ],
            [
                InlineKeyboardButton(text="⏱ Холд", callback_data=f"{CB_CATCON_EDIT}:{cat_id}:hold"),
                InlineKeyboardButton(text="💰 Цена", callback_data=f"{CB_CATCON_EDIT}:{cat_id}:price"),
            ],
            [InlineKeyboardButton(text=toggle_text, callback_data=f"{CB_CATCON_TOGGLE}:{cat_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{CB_CATCON_DELETE}:{cat_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=CB_CATCON_LIST)],
        ]
    )


def _delete_confirm_keyboard(cat_id: int, linked_count: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"{CB_CATCON_DELETE_YES}:{cat_id}")],
    ]
    if linked_count > 0:
        rows.append([
            InlineKeyboardButton(
                text=f"💣 Удалить вместе с {linked_count} карточк{'ой' if linked_count == 1 else 'ами'}",
                callback_data=f"{CB_CATCON_FORCE_DELETE_YES}:{cat_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"{CB_CATCON_DETAIL}:{cat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _edit_field_keyboard(cat_id: int, field: str) -> InlineKeyboardMarkup:
    """Клавиатура с пресетами для редактирования поля + отмена."""
    if field == "operator":
        rows = [
            [InlineKeyboardButton(text=op, callback_data=f"{CB_CATCON_EDIT}:{cat_id}:operator:{op}")]
            for op in OPERATORS
        ]
    elif field == "type":
        rows = [
            [InlineKeyboardButton(text=t, callback_data=f"{CB_CATCON_EDIT}:{cat_id}:type:{t}")]
            for t in SIM_TYPES
        ]
    elif field == "hold":
        rows = [
            [InlineKeyboardButton(text=h, callback_data=f"{CB_CATCON_EDIT}:{cat_id}:hold:{h}")]
            for h in HOLD_OPTIONS
        ]
    else:
        rows = []
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{CB_CATCON_DETAIL}:{cat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Утилиты ────────────────────────────────────────────────────

def _parse_price(raw: str) -> Decimal:
    value = raw.strip().replace(",", ".")
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\d.]", "", value)
    return Decimal(value)


def _collected_data(data: dict) -> dict[str, str]:
    """Собирает уже заполненные поля для отображения в прогрессе."""
    result: dict[str, str] = {}
    if data.get("operator"):
        result["📡 Оператор"] = data["operator"]
    if data.get("sim_type"):
        result["📂 Тип"] = data["sim_type"]
    if data.get("hold"):
        result["⏱ Холд"] = data["hold"]
    return result


def _render_cat_detail(cat) -> str:
    """Рендер карточки категории."""
    state = "✅ Активна" if cat.is_active else "⛔ Выключена"
    lines = [
        f"⚙️ <b>Категория #{cat.id}</b>",
        "",
        f"📡 Оператор: <b>{cat.operator or '—'}</b>",
        f"📂 Тип: <b>{cat.sim_type or '—'}</b>",
        f"⏱ Холд: <b>{cat.hold_condition or '—'}</b>",
        f"💰 Цена: <b>{cat.payout_rate} USDT</b>",
        f"📊 Статус: {state}",
        f"🏷 Заголовок: {cat.title}",
    ]
    return "\n".join(lines)


def _recompose_title(cat) -> str:
    """Пересобрать заголовок из компонентов."""
    parts = [cat.operator or "?", cat.sim_type or "?", cat.hold_condition or "?"]
    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════════
#  /adm_cat — точка входа
# ═══════════════════════════════════════════════════════════════════


@router.message(Command("adm_cat"))
async def on_adm_cat(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Главное меню конструктора категорий (только Chief Admin)."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(message.from_user.id):
        await message.answer("⛔ Недостаточно прав. Только для Chief Admin.")
        return

    await state.clear()
    categories = await CategoryService(session=session).get_all_categories()
    text = _r.render_cat_list(categories)
    await message.answer(text, parse_mode="HTML", reply_markup=_catcon_home_keyboard())


# ═══════════════════════════════════════════════════════════════════
#  Список категорий
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data == CB_CATCON_LIST)
async def on_cat_list(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await state.clear()
    categories = await CategoryService(session=session).get_all_categories()
    text = _r.render_cat_list(categories)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_cat_list_keyboard(categories),
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════
#  Детали категории
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_DETAIL}:"))
async def on_cat_detail(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    await state.clear()
    cat_id = int(callback.data.split(":")[2])
    cat = await CategoryService(session=session).get_by_id(cat_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    text = _render_cat_detail(cat)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_cat_detail_keyboard(cat_id, cat.is_active),
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════
#  Тоггл категории (вкл/выкл)
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_TOGGLE}:"))
async def on_cat_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    cat_id = int(callback.data.split(":")[2])
    cat = await CategoryService(session=session).get_by_id(cat_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await CategoryService(session=session).set_active(cat_id, not cat.is_active)
    new_state = "выключена ⛔" if cat.is_active else "включена ✅"
    await callback.answer(f"{cat.title}: {new_state}")

    cat = await CategoryService(session=session).get_by_id(cat_id)
    if cat is not None:
        text = _render_cat_detail(cat)
        await edit_message_text_safe(
            callback.message, text, parse_mode="HTML",
            reply_markup=_cat_detail_keyboard(cat_id, cat.is_active),
        )


# ═══════════════════════════════════════════════════════════════════
#  Удаление категории
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_DELETE}:"))
async def on_cat_delete_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    cat_id = int(callback.data.split(":")[2])
    cat_svc = CategoryService(session=session)
    cat = await cat_svc.get_by_id(cat_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    linked_count = await cat_svc.get_total_uploaded_count(cat_id)
    warning = (
        f"\n\n⚠️ С категорией связано <b>{linked_count}</b> карточек."
        if linked_count > 0
        else "\n\n⚠️ Это действие необратимо."
    )
    text = (
        f"🗑 <b>Удалить категорию?</b>\n\n"
        f"<b>{cat.title}</b> · {cat.payout_rate} USDT"
        + warning
    )
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_delete_confirm_keyboard(cat_id, linked_count),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_CATCON_DELETE_YES}:"))
async def on_cat_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    cat_id = int(callback.data.split(":")[2])
    result = await CategoryService(session=session).delete_category(cat_id)
    if result == "not_found":
        await callback.answer("Категория не найдена", show_alert=True)
        return
    if result == "deleted":
        await callback.answer("🗑 Категория удалена")
    else:
        await callback.answer("Категория связана с карточками и была выключена")
    categories = await CategoryService(session=session).get_all_categories()
    text = _r.render_cat_list(categories)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_cat_list_keyboard(categories),
    )


@router.callback_query(F.data.startswith(f"{CB_CATCON_FORCE_DELETE_YES}:"))
async def on_cat_force_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    cat_id = int(callback.data.split(":")[2])
    result = await CategoryService(session=session).force_delete_category(cat_id)
    if result == "not_found":
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await callback.answer("💣 Категория и все карточки удалены")
    categories = await CategoryService(session=session).get_all_categories()
    text = _r.render_cat_list(categories)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_cat_list_keyboard(categories),
    )


# ═══════════════════════════════════════════════════════════════════
#  Редактирование категории
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_EDIT}:"))
async def on_cat_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    # catcon:edit:{id}:{field} или catcon:edit:{id}:{field}:{value}
    parts = callback.data.split(":")
    cat_id = int(parts[2])
    field = parts[3]

    cat_svc = CategoryService(session=session)
    cat = await cat_svc.get_by_id(cat_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    # Если пресет-значение передано — применяем сразу
    if len(parts) >= 5:
        preset_val = ":".join(parts[4:])
        if preset_val == "Другое":
            return await _start_text_edit(callback, state, cat_id, field)

        if field == "operator":
            cat.operator = preset_val
        elif field == "type":
            cat.sim_type = preset_val
        elif field == "hold":
            cat.hold_condition = preset_val
        cat.title = _recompose_title(cat)
        await session.commit()
        await callback.answer("✅ Сохранено")

        await session.refresh(cat)
        text = _render_cat_detail(cat)
        await edit_message_text_safe(
            callback.message, text, parse_mode="HTML",
            reply_markup=_cat_detail_keyboard(cat_id, cat.is_active),
        )
        return

    # Нет значения — показать выбор
    if field == "price":
        return await _start_text_edit(callback, state, cat_id, field)

    field_titles = {"operator": "📡 Оператор", "type": "📂 Тип", "hold": "⏱ Холд"}
    current = {"operator": cat.operator, "type": cat.sim_type, "hold": cat.hold_condition}.get(field, "—")
    text = (
        f"✏️ <b>Редактирование: {field_titles.get(field, field)}</b>\n\n"
        f"Текущее: <b>{current or '—'}</b>\n\n"
        f"Выберите новое значение:"
    )
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_edit_field_keyboard(cat_id, field),
    )
    await callback.answer()


async def _start_text_edit(
    callback: CallbackQuery, state: FSMContext, cat_id: int, field: str,
) -> None:
    """Переводит в FSM для текстового ввода."""
    await state.clear()
    await state.update_data(edit_cat_id=cat_id, edit_field=field)
    await state.set_state(CatConstructorState.edit_price)

    if field == "price":
        prompt = "Введите новую цену в USDT (например <code>1.50</code>):"
    elif field == "operator":
        prompt = "Введите нового оператора текстом:"
    elif field == "type":
        prompt = "Введите новый тип текстом:"
    else:
        prompt = "Введите новое значение холда текстом:"

    text = f"✏️ <b>Редактирование</b>\n\n{prompt}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"{CB_CATCON_DETAIL}:{cat_id}")]]
    )
    await edit_message_text_safe(callback.message, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.message(CatConstructorState.edit_price, F.text)
async def on_edit_text_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Текстовый ввод для редактирования поля категории."""
    if message.text is None:
        return
    data = await state.get_data()
    cat_id = data.get("edit_cat_id")
    field = data.get("edit_field")
    if not isinstance(cat_id, int) or not isinstance(field, str):
        await state.clear()
        await message.answer("Ошибка состояния. Введите /adm_cat заново.")
        return

    cat_svc = CategoryService(session=session)
    cat = await cat_svc.get_by_id(cat_id)
    if cat is None:
        await state.clear()
        await message.answer("Категория не найдена.")
        return

    raw = message.text.strip()

    if field == "price":
        try:
            price = _parse_price(raw)
        except (InvalidOperation, ValueError):
            await message.answer("❌ Неверный формат. Число, например <code>1.50</code>", parse_mode="HTML")
            return
        if price <= 0:
            await message.answer("❌ Цена должна быть больше 0.")
            return
        await cat_svc.update_payout_rate(cat_id, price)
    elif field == "operator":
        val = raw[:60]
        if len(val) < 2:
            await message.answer("Минимум 2 символа.")
            return
        cat.operator = val
        cat.title = _recompose_title(cat)
        await session.commit()
    elif field == "type":
        val = raw[:60]
        if len(val) < 2:
            await message.answer("Минимум 2 символа.")
            return
        cat.sim_type = val
        cat.title = _recompose_title(cat)
        await session.commit()
    elif field == "hold":
        val = raw[:60]
        if len(val) < 2:
            await message.answer("Минимум 2 символа.")
            return
        cat.hold_condition = val
        cat.title = _recompose_title(cat)
        await session.commit()

    await state.clear()
    cat = await cat_svc.get_by_id(cat_id)
    if cat is None:
        await message.answer("Категория не найдена.")
        return
    text = _render_cat_detail(cat)
    await message.answer(
        f"✅ Сохранено\n\n{text}", parse_mode="HTML",
        reply_markup=_cat_detail_keyboard(cat_id, cat.is_active),
    )


# ═══════════════════════════════════════════════════════════════════
#  Шаг A: Оператор
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_OPERATOR}:"))
async def on_step_operator(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    val = callback.data.split(":", 2)[2]
    if val == "_start":
        # Начало конструктора — показать шаг 1
        await state.clear()
        await state.set_state(CatConstructorState.step_operator)
        text = _r.render_cat_constructor_step(
            1, 3, "Оператор", "Выберите оператора из списка или введите свой:",
        )
        await edit_message_text_safe(
            callback.message, text, parse_mode="HTML",
            reply_markup=_operator_keyboard(),
        )
        await callback.answer()
        return

    # Оператор выбран из пресета
    await state.update_data(operator=val)
    await state.set_state(CatConstructorState.step_type)
    data = await state.get_data()
    text = _r.render_cat_constructor_step(
        2, 3, "Тип симки", "Выберите тип:", current_data=_collected_data(data),
    )
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_type_keyboard(),
    )
    await callback.answer()


@router.message(CatConstructorState.step_operator, F.text)
async def on_step_operator_text(message: Message, state: FSMContext) -> None:
    """Ввод оператора вручную."""
    if message.text is None:
        return
    val = message.text.strip()[:60]
    if len(val) < 2:
        await message.answer("Слишком короткое. Минимум 2 символа.")
        return
    await state.update_data(operator=val)
    await state.set_state(CatConstructorState.step_type)
    data = await state.get_data()
    text = _r.render_cat_constructor_step(
        2, 3, "Тип симки", "Выберите тип:", current_data=_collected_data(data),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_type_keyboard())


# ═══════════════════════════════════════════════════════════════════
#  Шаг B: Тип
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_CATCON_TYPE}:"))
async def on_step_type(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data is None or callback.message is None:
        return
    val = callback.data.split(":", 2)[2]

    if val == "Другое":
        await state.set_state(CatConstructorState.step_type)
        await edit_message_text_safe(
            callback.message,
            _r.render_cat_constructor_step(
                2, 3, "Тип симки", "Введите свой тип текстом:",
                current_data=_collected_data(await state.get_data()),
            ),
            parse_mode="HTML", reply_markup=None,
        )
        await callback.answer()
        return

    await state.update_data(sim_type=val)
    await state.set_state(CatConstructorState.step_price)
    data = await state.get_data()
    text = _r.render_cat_constructor_step(
        3, 3, "Цена в USDT", "Введите цену числом (например 1.50):",
        current_data=_collected_data(data),
    )
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer()


@router.message(CatConstructorState.step_type, F.text)
async def on_step_type_text(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    val = message.text.strip()[:60]
    if len(val) < 2:
        await message.answer("Слишком короткое. Минимум 2 символа.")
        return
    await state.update_data(sim_type=val)
    await state.set_state(CatConstructorState.step_price)
    data = await state.get_data()
    text = _r.render_cat_constructor_step(
        3, 3, "Цена в USDT", "Введите цену числом (например 1.50):",
        current_data=_collected_data(data),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=None)


# ═══════════════════════════════════════════════════════════════════
#  Шаг C: Цена
# ═══════════════════════════════════════════════════════════════════


@router.message(CatConstructorState.step_price, F.text)
async def on_step_price(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    try:
        price = _parse_price(message.text)
    except (InvalidOperation, ValueError):
        await message.answer("❌ Неверный формат. Введите число, например <code>1.50</code>", parse_mode="HTML")
        return
    if price <= 0:
        await message.answer("❌ Цена должна быть больше 0.")
        return

    await state.update_data(price=str(price))
    await state.set_state(CatConstructorState.step_confirm)

    data = await state.get_data()
    text = _r.render_cat_constructor_confirm(
        operator=data["operator"],
        sim_type=data["sim_type"],
        price=str(price),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_confirm_keyboard())


# ═══════════════════════════════════════════════════════════════════
#  Подтверждение
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data == CB_CATCON_CONFIRM)
async def on_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    data = await state.get_data()
    await state.clear()

    operator = str(data.get("operator", ""))
    sim_type = str(data.get("sim_type", ""))
    price = Decimal(data.get("price", "0"))

    if not operator or not sim_type or price <= 0:
        await callback.answer("Ошибка данных. Начните заново.", show_alert=True)
        return

    composed_title = f"{operator} | {sim_type}"

    category = await AdminService(session=session).create_category(
        title=composed_title,
        payout_rate=price,
        description=f"Оператор: {operator}, Тип: {sim_type}",
    )

    # Сохраняем компоненты конструктора
    cat_svc = CategoryService(session=session)
    cat_obj = await cat_svc.get_by_id(category.id)
    if cat_obj is not None:
        cat_obj.operator = operator
        cat_obj.sim_type = sim_type
        cat_obj.hold_condition = None
        await session.commit()

    await callback.answer("✅ Категория создана!")

    categories = await cat_svc.get_all_categories()
    text = _r.render_cat_list(categories)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_cat_list_keyboard(categories),
    )


# ═══════════════════════════════════════════════════════════════════
#  Отмена
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data == CB_CATCON_CANCEL)
async def on_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    if callback.message is None:
        await callback.answer("Отменено")
        return
    categories = await CategoryService(session=session).get_all_categories()
    text = _r.render_cat_list(categories)
    await edit_message_text_safe(
        callback.message, text, parse_mode="HTML",
        reply_markup=_catcon_home_keyboard(),
    )
    await callback.answer("Отменено")
