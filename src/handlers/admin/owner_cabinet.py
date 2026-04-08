"""
Silver Sakura — Кабинет Владельца (/o).
Глобальный рефакторинг и оптимизация.
"""

from __future__ import annotations

import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, List, Any

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, CallbackQuery, FSInputFile, 
    InlineKeyboardMarkup, Message
)
from loguru import logger
from sqlalchemy import delete, func, or_, select

# Импорты проекта
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.filters.admin import IsOwnerFilter
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import CatConCD, CatManageCD, NavCD, OwnerUserCD
from src.keyboards.owner import (
    get_user_card_kb, get_owner_settings_kb, get_owner_categories_kb,
    get_owner_category_detail_kb, get_owner_monitoring_kb,
    get_owner_finance_kb, get_owner_users_kb, get_users_list_kb,
    get_catcon_main_kb
)
from src.services.admin_stats_service import AdminStatsService
from src.services.user_service import UserService
from src.utils.text_format import edit_message_text_or_caption_safe
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT, GDPXRenderer

if TYPE_CHECKING:
    pass

router = Router(name="owner-cabinet-router")
_renderer = GDPXRenderer()


# --- СОСТОЯНИЯ (FSM) ---

class OwnerStates(StatesGroup):
    """Общие состояния владельца."""
    waiting_for_broadcast = State()
    waiting_for_role_id = State()
    waiting_for_search_id = State()
    waiting_for_audit_query = State()
    waiting_for_cat_price = State()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (HELPERS) ---

async def _render_user_card(user: User, callback_data: OwnerUserCD) -> tuple[str, InlineKeyboardMarkup]:
    """Унифицированный рендеринг карточки пользователя."""
    from src.keyboards.owner import get_user_card_kb
    
    status_text = "🚫 ЗАБЛОКИРОВАН" if user.is_restricted else "🟢 АКТИВЕН"
    reg_date = user.created_at.strftime("%d.%m.%Y")
    
    text = (
        f"👤 <b>КАРТОЧКА ПОЛЬЗОВАТЕЛЯ</b>\n"
        f"{DIVIDER}\n"
        f"🆔 <b>TG ID:</b> <code>{user.telegram_id}</code>\n"
        f"👤 <b>User:</b> @{user.username or 'N/A'}\n"
        f"🏷️ <b>Роль:</b> <code>{user.role.value.upper()}</code>\n"
        f"📅 <b>Регистрация:</b> <code>{reg_date}</code>\n"
        f"📡 <b>Статус:</b> {status_text}\n"
        f"{DIVIDER_LIGHT}\n"
        f"💰 <b>Баланс:</b> <code>{user.pending_balance}</code> USDT\n"
        f"💎 <b>Всего выплачено:</b> <code>{user.total_paid}</code> USDT\n"
        f"{DIVIDER}\n"
        f"<i>Действия над пользователем:</i>"
    )
    kb = get_user_card_kb(user.id, user.role.value, user.is_restricted, callback_data.page, callback_data.role)
    return text, kb


async def _get_on_enter_owner_panel():
    """Ленивый импорт точки входа для предотвращения циклических зависимостей."""
    from src.handlers.admin import on_enter_owner_panel
    return on_enter_owner_panel


# --- НАВИГАЦИЯ ---

@router.callback_query(F.data == "owner_back_main", IsOwnerFilter())
async def cb_owner_back_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Универсальный возврат в главное меню владельца."""
    await state.clear()
    func = await _get_on_enter_owner_panel()
    await func(callback, session)
    await callback.answer()


# --- КОМАНДНЫЙ ЦЕНТР ---

@router.callback_query(F.data == "owner_cmd_center", IsOwnerFilter())
async def cb_owner_cmd_center(callback: CallbackQuery, session: AsyncSession):
    """Командный центр: Мониторинг модераторов и лог действий."""
    stats_svc = AdminStatsService(session)
    online_mods = await stats_svc.get_online_moderators(minutes=30)
    recent_actions = await stats_svc.get_recent_moderation_actions(limit=10)

    text_lines = [
        "🏯 <b>КОМАНДНЫЙ ЦЕНТР // МОНИТОРИНГ</b>",
        DIVIDER,
        "👤 <b>МОДЕРАТОРЫ ОНЛАЙН:</b>"
    ]

    if not online_mods:
        text_lines.append(" <i>Нет активных модераторов (30м)</i>")
    else:
        for m in online_mods:
            last_m = int((datetime.now(timezone.utc) - m['last_active']).total_seconds() / 60)
            text_lines.append(f" ├ @{m['username']} <code>({last_m}м назад)</code>")

    text_lines.append(f"\n{DIVIDER_LIGHT}")
    text_lines.append("📜 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ:</b>")

    for a in recent_actions:
        time_str = a['time'].strftime("%H:%M")
        status_icon = "✅" if a['to_status'] == SubmissionStatus.ACCEPTED else "❌"
        target = f"...{a['phone'][-4:]}" if a['phone'] and a['phone'] != "N/A" else f"#{a['sub_id']}"
        text_lines.append(f" ├ <code>[{time_str}]</code> {status_icon} <b>@{a['admin']}</b> → {target}")

    text_lines.append(f"\n{DIVIDER}\n<i>Управление модерацией и логами.</i>")

    kb = (PremiumBuilder()
          .button("🛑 ПРИОСТАНОВИТЬ ВСЕХ", "owner_mods_suspend")
          .button("▶️ ВОЗОБНОВИТЬ ВСЕХ", "owner_mods_resume")
          .button("🔄 ОБНОВИТЬ ЛОГ", "owner_cmd_center")
          .adjust(2, 1)
          .back("owner_back_main")
          .as_markup())

    await edit_message_text_or_caption_safe(callback.message, "\n".join(text_lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer("🔄 Данные обновлены")


@router.callback_query(F.data.in_(["owner_mods_suspend", "owner_mods_resume"]), IsOwnerFilter())
async def cb_owner_mods_control(callback: CallbackQuery, session: AsyncSession):
    """Глобальное управление работой модераторов."""
    from src.core.config import get_settings
    settings = get_settings()
    is_suspended = (callback.data == "owner_mods_suspend")
    settings.moderation_suspended = is_suspended
    
    msg = "🛑 Работа модераторов ПРИОСТАНОВЛЕНА" if is_suspended else "▶️ Работа модераторов ВОЗОБНОВЛЕНА"
    await callback.answer(msg, show_alert=True)
    await cb_owner_monitoring(callback, session)


# --- ФИНАНСЫ ---

@router.callback_query(F.data == "owner_finance", IsOwnerFilter())
async def cb_owner_finance(callback: CallbackQuery, session: AsyncSession):
    """Раздел выплат и финансов."""
    stats_svc = AdminStatsService(session)
    stats = await stats_svc.get_owner_summary_stats()
    
    stmt = select(User).where(User.pending_balance > 0).order_by(User.pending_balance.desc()).limit(10)
    pending_sellers = (await session.execute(stmt)).scalars().all()
    
    text = _renderer.render_owner_finance(stats, pending_sellers)
    
    from src.keyboards.owner import get_owner_finance_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_finance_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "owner_finance_topup", IsOwnerFilter())
async def cb_owner_finance_topup(callback: CallbackQuery, session: AsyncSession):
    """Переход к пополнению баланса выплат."""
    from src.handlers.finance.payouts import cmd_topup_start
    await cmd_topup_start(callback.message, session)
    await callback.answer()


# --- ПОЛЬЗОВАТЕЛИ ---

@router.callback_query(OwnerUserCD.filter(F.action == "main"), IsOwnerFilter())
@router.callback_query(F.data == "owner_users", IsOwnerFilter())
async def cb_owner_users_main(callback: CallbackQuery, session: AsyncSession):
    """Главное меню раздела пользователей."""
    sellers = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.SELLER))
    admins = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
    
    text = (
        "👥 <b>ПОЛЬЗОВАТЕЛИ И МОДЕРАТОРЫ</b>\n\n"
        f" ├ Селлеров: <code>{sellers}</code>\n"
        f" └ Модераторов: <code>{admins}</code>\n\n"
        "<i>Выберите категорию для управления:</i>"
    )
    from src.keyboards.owner import get_owner_users_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_users_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(OwnerUserCD.filter(F.action == "list"), IsOwnerFilter())
@router.callback_query(F.data.startswith("ow_user_pg:"), IsOwnerFilter())
async def cb_owner_users_list(callback: CallbackQuery, callback_data: OwnerUserCD | str, session: AsyncSession):
    """Список пользователей с пагинацией."""
    if isinstance(callback_data, str):
        p = callback_data.split(":")
        page, role_str = int(p[2]), p[3]
    else:
        page, role_str = callback_data.page, callback_data.role
        
    target_role = {"seller": UserRole.SELLER, "admin": UserRole.ADMIN}.get(role_str)
    users, total = await AdminStatsService(session).get_users_paginated(page=page, role=target_role)
    
    from src.keyboards.owner import get_users_list_kb
    text = f"👥 <b>СПИСОК ПОЛЬЗОВАТЕЛЕЙ ({role_str.upper()})</b>"
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_users_list_kb(users, page, total, role_str), parse_mode="HTML")
    await callback.answer()


@router.callback_query(OwnerUserCD.filter(F.action == "view"), IsOwnerFilter())
async def cb_owner_user_card(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession):
    """Детальный просмотр пользователя."""
    user = await session.get(User, callback_data.user_id)
    if user:
        text, kb = await _render_user_card(user, callback_data)
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(OwnerUserCD.filter(F.action.in_(["role", "status"])), IsOwnerFilter())
async def cb_owner_user_actions(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession):
    """Быстрые действия над пользователем."""
    user = await session.get(User, callback_data.user_id)
    if not user: return await callback.answer("❌ Не найден", show_alert=True)

    if callback_data.action == "role":
        user.role = UserRole.ADMIN if user.role == UserRole.SELLER else UserRole.SELLER
    elif callback_data.action == "status":
        user.is_restricted = not user.is_restricted
        
    await session.commit()
    await cb_owner_user_card(callback, callback_data, session)
    await callback.answer("✅ Сохранено")


@router.callback_query(F.data == "owner_users_search", IsOwnerFilter())
async def cb_owner_users_search(callback: CallbackQuery, state: FSMContext):
    """Поиск пользователя по ID."""
    await state.set_state(OwnerStates.waiting_for_search_id)
    kb = (PremiumBuilder().back("owner_users", "❌ ОТМЕНА").as_markup())
    await edit_message_text_or_caption_safe(callback.message, "🔍 <b>Введите Telegram ID или системный ID:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(OwnerStates.waiting_for_search_id, IsOwnerFilter())
async def process_owner_user_search(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ввода ID."""
    if not message.text.isdigit(): return await message.answer("❌ Введите число.")
    
    tid = int(message.text)
    user = await session.get(User, tid) or await UserService(session).get_by_telegram_id(tid)
    
    if user:
        await state.clear()
        text, kb = await _render_user_card(user, OwnerUserCD(action="view", user_id=user.id, role="all", page=0))
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer("🔍 Пользователь не найден. Попробуйте другой ID.")


# --- КАТЕГОРИИ ---

@router.callback_query(F.data == "owner_categories", IsOwnerFilter())
async def cb_owner_categories(callback: CallbackQuery, session: AsyncSession):
    """Управление категориями и ставками."""
    stmt = select(Category).order_by(Category.is_priority.desc(), Category.title.asc())
    categories = (await session.execute(stmt)).scalars().all()
    
    from src.keyboards.owner import get_owner_categories_kb
    text = "🏷️ <b>КАТЕГОРИИ И СТАВКИ</b>\n\nУправление тарифами выкупа eSIM и приоритетами."
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_categories_kb(categories), parse_mode="HTML")
    await callback.answer()


@router.callback_query(CatManageCD.filter(F.action == "view"), IsOwnerFilter())
async def cb_owner_category_view(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession):
    """Детальный просмотр категории."""
    cat = await session.get(Category, callback_data.cat_id)
    if not cat: return await callback.answer("❌ Не найдена", show_alert=True)
    
    pending = await session.scalar(select(func.count(Submission.id)).where(Submission.category_id == cat.id, Submission.status == SubmissionStatus.PENDING))
    status = "🟢 АКТИВНА" if cat.is_active else "🔴 ОТКЛЮЧЕНА"
    prio = "🏮 ВЫСОКИЙ" if cat.is_priority else "⚪️ ОБЫЧНЫЙ"
    
    text = (
        f"🏷️ <b>КАТЕГОРИЯ: {cat.title}</b>\n{DIVIDER}\n"
        f"💰 <b>Ставка:</b> <code>{cat.payout_rate}</code> USDT\n"
        f"📡 <b>Статус:</b> {status}\n"
        f"⚖️ <b>Приоритет:</b> {prio}\n"
        f"📦 <b>В очереди:</b> <code>{pending}</code> шт.\n"
        f"{DIVIDER_LIGHT}\n<i>Настройте параметры выкупа:</i>"
    )
    from src.keyboards.owner import get_owner_category_detail_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_category_detail_kb(cat.id, cat.is_active, cat.is_priority), parse_mode="HTML")
    await callback.answer()


@router.callback_query(CatManageCD.filter(F.action == "edit_price"), IsOwnerFilter())
async def cb_owner_cat_price_start(callback: CallbackQuery, callback_data: CatManageCD, state: FSMContext):
    await state.update_data(edit_cat_id=callback_data.cat_id)
    await state.set_state(OwnerStates.waiting_for_cat_price)
    kb = (PremiumBuilder().back(CatManageCD(action="view", cat_id=callback_data.cat_id), "❌ ОТМЕНА").as_markup())
    await edit_message_text_or_caption_safe(callback.message, "💰 <b>Введите новую цену (USDT):</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(OwnerStates.waiting_for_cat_price, IsOwnerFilter())
async def process_owner_cat_price(message: Message, state: FSMContext, session: AsyncSession):
    try:
        new_price = Decimal(message.text.strip().replace(",", "."))
        cat_id = (await state.get_data()).get("edit_cat_id")
        cat = await session.get(Category, cat_id)
        if cat:
            cat.payout_rate = new_price
            await session.commit()
            await message.answer(f"✅ Ставка <b>{cat.title}</b> обновлена до <code>{new_price}</code> USDT")
            
            # Показываем список категорий заново (без вызова callback-хендлера напрямую)
            stmt = select(Category).order_by(Category.is_priority.desc(), Category.title.asc())
            categories = (await session.execute(stmt)).scalars().all()
            await message.answer(
                "🏷️ <b>КАТЕГОРИИ И СТАВКИ</b>\n\nУправление тарифами выкупа eSIM и приоритетами.",
                reply_markup=get_owner_categories_kb(categories),
                parse_mode="HTML"
            )
    except:
        await message.answer("❌ Ошибка ввода. Введите число.")
    await state.clear()


@router.callback_query(CatManageCD.filter(F.action.in_(["toggle_active", "toggle_priority"])), IsOwnerFilter())
async def cb_owner_cat_toggles(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession):
    cat = await session.get(Category, callback_data.cat_id)
    if cat:
        if callback_data.action == "toggle_active": cat.is_active = not cat.is_active
        else: cat.is_priority = not cat.is_priority
        await session.commit()
        await cb_owner_category_view(callback, callback_data, session)
    await callback.answer("✅ Обновлено")


# --- МОНИТОРИНГ ---

@router.callback_query(F.data == "owner_monitoring", IsOwnerFilter())
async def cb_owner_monitoring(callback: CallbackQuery, session: AsyncSession):
    """Живой мониторинг системы."""
    from src.core.config import get_settings
    settings, stats_svc = get_settings(), AdminStatsService(session)
    
    summary = await stats_svc.get_owner_summary_stats()
    online = await stats_svc.get_online_moderators(minutes=15)
    actions = await stats_svc.get_recent_moderation_actions(limit=15)
    
    m_status = "🔴 ПРИОСТАНОВЛЕНА" if getattr(settings, "moderation_suspended", False) else "🟢 АКТИВНА"
    main_status = "🛠 ВКЛЮЧЕН" if settings.maintenance_mode else "📡 ВЫКЛЮЧЕН"
    
    text = (
        f"🚨 <b>МОНИТОРИНГ LIVE</b>\n{DIVIDER}\n"
        f"⚙️ <b>РЕЖИМЫ:</b>\n ├ Модерация: {m_status}\n └ Обслуживание: {main_status}\n"
        f"{DIVIDER_LIGHT}\n"
        f"⏳ <b>ОЧЕРЕДЬ:</b> <code>{summary.get('total_pending', 0)}</code>\n"
        f"👥 <b>ОНЛАЙН:</b> <code>{len(online)}</code> модераторов\n"
        f"{DIVIDER_LIGHT}\n<b>ЛОГ ДЕЙСТВИЙ:</b>\n"
    )
    text += "\n".join([f"├ <code>[{a['time'].strftime('%H:%M')}]</code> @{a['admin']} → #{a['sub_id']}" for a in actions])
    
    from src.keyboards.owner import get_owner_monitoring_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_monitoring_kb(), parse_mode="HTML")
    await callback.answer("🔄 Данные обновлены")


@router.callback_query(F.data == "owner_settings_maintenance", IsOwnerFilter())
async def cb_owner_settings_maint(callback: CallbackQuery, session: AsyncSession):
    from src.core.config import get_settings
    s = get_settings()
    s.maintenance_mode = not s.maintenance_mode
    await callback.answer(f"Режим обслуживания: {'ВКЛ' if s.maintenance_mode else 'ВЫКЛ'}", show_alert=True)
    await cb_owner_monitoring(callback, session)


# --- БЕЗОПАСНОСТЬ (ДОПОЛНИТЕЛЬНО) ---

@router.callback_query(F.data == "owner_sec_export", IsOwnerFilter())
async def cb_owner_export_logs(callback: CallbackQuery, bot: Bot):
    log_path = "logs/admin_actions.log"
    if os.path.exists(log_path):
        try:
            await callback.answer("📤 Отправка...")
            file = FSInputFile(log_path, filename=f"actions_{datetime.now().strftime('%H%M')}.log")
            await bot.send_document(callback.message.chat.id, file, caption="📜 GDPX LOGS")
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {str(e)[:40]}", show_alert=True)
    else:
        await callback.answer("❌ Файл не найден", show_alert=True)


# --- РАССЫЛКА ---

@router.callback_query(F.data == "owner_settings_notify", IsOwnerFilter())
async def cb_owner_broadcast_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerStates.waiting_for_broadcast)
    kb = (PremiumBuilder().back("owner_settings", "❌ ОТМЕНА").as_markup())
    await edit_message_text_or_caption_safe(callback.message, "📢 <b>Введите текст/фото для рассылки:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(OwnerStates.waiting_for_broadcast, IsOwnerFilter())
async def process_owner_broadcast(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    ids = (await session.execute(select(User.telegram_id))).scalars().all()
    count = 0
    for uid in ids:
        try:
            await message.copy_to(uid)
            count += 1
        except: continue
    await message.answer(f"✅ Рассылка завершена: <code>{count}</code> чел.")


# --- НАСТРОЙКИ (ОСТАЛЬНОЕ) ---

@router.callback_query(F.data == "owner_settings", IsOwnerFilter())
async def cb_owner_settings_root(callback: CallbackQuery):
    from src.core.config import get_settings
    m_mode = getattr(get_settings(), "maintenance_mode", False)
    from src.keyboards.owner import get_owner_settings_kb
    await edit_message_text_or_caption_safe(callback.message, "⚙️ <b>НАСТРОЙКИ СИСТЕМЫ</b>", reply_markup=get_owner_settings_kb(m_mode), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["owner_stats_platform", "owner_stats_mods", "owner_stats_sellers"]), IsOwnerFilter())
async def cb_owner_stats_view(callback: CallbackQuery, session: AsyncSession):
    svc = AdminStatsService(session)
    now = datetime.now(timezone.utc)
    if "platform" in callback.data:
        res = await svc.get_platform_stats(now - timedelta(days=30), now)
        text = _renderer.render_platform_analytics(res)
    elif "mods" in callback.data:
        res = await svc.get_moderators_performance(now - timedelta(days=30), now)
        text = _renderer.render_moderators_stats(res)
    else:
        res = await svc.get_top_sellers_extended(now - timedelta(days=30), now)
        text = _renderer.render_sellers_leaderboard_owner(res)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=PremiumBuilder().back("owner_stats").as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["owner_finance_bulk", "owner_finance_audit", "owner_lb_prizes"]), IsOwnerFilter())
async def cb_owner_placeholders(callback: CallbackQuery):
    await callback.answer("🏗️ В разработке (Этап 7+)", show_alert=True)
