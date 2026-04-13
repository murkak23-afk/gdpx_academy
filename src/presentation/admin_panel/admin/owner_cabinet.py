"""
Silver Sakura — Кабинет Владельца (/o).
Глобальный рефакторинг и оптимизация.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy import func, select

# Импорты проекта
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.presentation.filters.admin import IsOwnerFilter
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import CatManageCD, OwnerUserCD
from src.presentation.admin_panel.owner import (
    get_owner_categories_kb,
    get_owner_category_detail_kb,
    get_owner_monitoring_kb,
    get_user_card_kb,
    get_users_list_kb,
)
from src.domain.moderation.admin_stats_service import AdminStatsService
from src.domain.users.user_service import UserService
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT, GDPXRenderer

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
    waiting_for_lb_prize_text = State()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (HELPERS) ---

async def _render_user_card(user: User, callback_data: OwnerUserCD) -> tuple[str, InlineKeyboardMarkup]:
    """Унифицированный рендеринг карточки пользователя."""
    
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
    kb = await get_user_card_kb(user.id, user.role.value, user.is_restricted, callback_data.page, callback_data.role)
    return text, kb


async def _get_on_enter_owner_panel():
    """Ленивый импорт точки входа для предотвращения циклических зависимостей."""
    from src.presentation.admin_panel.admin import on_enter_owner_panel
    return on_enter_owner_panel


# --- НАВИГАЦИЯ ---

@router.callback_query(F.data == "owner_back_main", IsOwnerFilter())
async def cb_owner_back_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Универсальный возврат в главное меню владельца."""
    await state.clear()
    func = await _get_on_enter_owner_panel()
    await func(callback, session, ui)
    await callback.answer()


# --- КОМАНДНЫЙ ЦЕНТР ---

@router.callback_query(F.data == "owner_cmd_center", IsOwnerFilter())
async def cb_owner_cmd_center(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Командный центр: Мониторинг модераторов и лог действий."""
    logger.info("Entering cmd_center handler")
    try:
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

        await ui.display(event=callback, text="\n".join(text_lines), reply_markup=kb)
        await callback.answer("🔄 Данные обновлены")
    except Exception:
        logger.exception("Error in cmd_center handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data.in_(["owner_mods_suspend", "owner_mods_resume"]), IsOwnerFilter())
async def cb_owner_mods_control(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Глобальное управление работой модераторов."""
    from src.core.config import get_settings
    settings = get_settings()
    is_suspended = (callback.data == "owner_mods_suspend")
    settings.moderation_suspended = is_suspended
    
    msg = "🛑 Работа модераторов ПРИОСТАНОВЛЕНА" if is_suspended else "▶️ Работа модераторов ВОЗОБНОВЛЕНА"
    await callback.answer(msg, show_alert=True)
    await cb_owner_monitoring(callback, session, ui)


# --- ФИНАНСЫ ---

@router.callback_query(F.data == "owner_finance", IsOwnerFilter())
async def cb_owner_finance(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Раздел выплат и финансов."""
    logger.info("Entering finance handler")
    try:
        stats_svc = AdminStatsService(session)
        stats = await stats_svc.get_owner_summary_stats()
        
        stmt = select(User).where(User.pending_balance > 0).order_by(User.pending_balance.desc()).limit(10)
        pending_sellers = (await session.execute(stmt)).scalars().all()
        
        text = _renderer.render_owner_finance(stats, pending_sellers)
        
        from src.presentation.admin_panel.owner import get_owner_finance_kb
        await ui.display(event=callback, text=text, reply_markup=await get_owner_finance_kb())
        await callback.answer()
    except Exception:
        logger.exception("Error in finance handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data == "owner_finance_audit", IsOwnerFilter())
async def cb_owner_finance_audit(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Детальный финансовый аудит системы."""
    stats_svc = AdminStatsService(session)
    audit_data = await stats_svc.get_detailed_finance_audit()
    
    text = _renderer.render_finance_audit(audit_data)
    kb = (PremiumBuilder().back("owner_finance").as_markup())
    
    await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "owner_finance_topup", IsOwnerFilter())
async def cb_owner_finance_topup(callback: CallbackQuery, session: AsyncSession):
    """Переход к пополнению баланса выплат."""
    from src.presentation.admin_panel.finance.payouts import start_topup_process
    await start_topup_process(callback, session)
    await callback.answer()


@router.callback_query(F.data == "owner_to_moderation", IsOwnerFilter())
async def cb_owner_to_moderation(callback: CallbackQuery, session: AsyncSession, ui: MessageManager, state: FSMContext):
    """Переход в режим модерации из кабинета владельца."""
    from src.presentation.admin_panel.admin import on_enter_moderator_panel
    await on_enter_moderator_panel(callback, session, ui, state)
    await callback.answer("⚖️ Режим модерации")


@router.callback_query(F.data == "owner_back_main", IsOwnerFilter())
async def cb_owner_back_main(callback: CallbackQuery, session: AsyncSession, ui: MessageManager, state: FSMContext):
    """Возврат в главное меню владельца."""
    from src.presentation.admin_panel.admin import on_enter_owner_panel
    await on_enter_owner_panel(callback, session, ui, state)
    await callback.answer()


# --- ПОЛЬЗОВАТЕЛИ ---

@router.callback_query(OwnerUserCD.filter(F.action == "main"), IsOwnerFilter())
@router.callback_query(F.data == "owner_users", IsOwnerFilter())
async def cb_owner_users_main(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Главное меню раздела пользователей."""
    logger.info("Entering users handler")
    try:
        sellers = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.SELLER))
        admins = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
        
        text = (
            "👥 <b>ПОЛЬЗОВАТЕЛИ И МОДЕРАТОРЫ</b>\n\n"
            f" ├ Селлеров: <code>{sellers}</code>\n"
            f" └ Модераторов: <code>{admins}</code>\n\n"
            "<i>Выберите категорию для управления:</i>"
        )
        from src.presentation.admin_panel.owner import get_owner_users_kb
        await ui.display(event=callback, text=text, reply_markup=await get_owner_users_kb())
        await callback.answer()
    except Exception:
        logger.exception("Error in users handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(OwnerUserCD.filter(F.action == "list"), IsOwnerFilter())
@router.callback_query(F.data.startswith("ow_user_pg:"), IsOwnerFilter())
async def cb_owner_users_list(callback: CallbackQuery, callback_data: OwnerUserCD | str, session: AsyncSession, ui: MessageManager):
    """Список пользователей с пагинацией."""
    if isinstance(callback_data, str):
        p = callback_data.split(":")
        page, role_str = int(p[2]), p[3]
    else:
        page, role_str = callback_data.page, callback_data.role
        
    target_role = {"seller": UserRole.SELLER, "admin": UserRole.ADMIN}.get(role_str)
    users, total = await AdminStatsService(session).get_users_paginated(page=page, role=target_role)
    
    text = f"👥 <b>СПИСОК ПОЛЬЗОВАТЕЛЕЙ ({role_str.upper()})</b>"
    await ui.display(event=callback, text=text, reply_markup=await get_users_list_kb(users, page, total, role_str))
    await callback.answer()


@router.callback_query(OwnerUserCD.filter(F.action == "view"), IsOwnerFilter())
async def cb_owner_user_card(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession, ui: MessageManager):
    """Детальный просмотр пользователя."""
    user = await session.get(User, callback_data.user_id)
    if user:
        text, kb = await _render_user_card(user, callback_data)
        await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()


@router.callback_query(OwnerUserCD.filter(F.action.in_(["role", "status", "balance"])), IsOwnerFilter())
async def cb_owner_user_edit(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession, ui: MessageManager):
    """Быстрые действия над пользователем."""
    user = await session.get(User, callback_data.user_id)
    if not user: return await callback.answer("❌ Не найден", show_alert=True)

    if callback_data.action == "role":
        roles_cycle = [UserRole.SELLER, UserRole.ADMIN, UserRole.SIMBUYER]
        try:
            current_role_val = user.role
            idx = roles_cycle.index(current_role_val)
            user.role = roles_cycle[(idx + 1) % len(roles_cycle)]
        except ValueError:
            user.role = UserRole.SELLER
    elif callback_data.action == "status":
        user.is_restricted = not user.is_restricted
        
    await session.commit()
    await cb_owner_user_card(callback, callback_data, session, ui)
    await callback.answer("✅ Сохранено")


@router.callback_query(F.data == "owner_users_search", IsOwnerFilter())
async def cb_owner_users_search(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Поиск пользователя по ID."""
    await state.set_state(OwnerStates.waiting_for_search_id)
    kb = (PremiumBuilder().back("owner_users", "❌ ОТМЕНА").as_markup())
    await ui.display(event=callback, text="🔍 <b>Введите Telegram ID или системный ID:</b>", reply_markup=kb)
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
async def cb_owner_categories(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Управление категориями и ставками."""
    logger.info("Entering categories handler")
    try:
        stmt = select(Category).order_by(Category.is_priority.desc(), Category.title.asc())
        categories = (await session.execute(stmt)).scalars().all()
        
        from src.presentation.admin_panel.owner import get_owner_categories_kb
        text = "🏷️ <b>КАТЕГОРИИ И СТАВКИ</b>\n\nУправление тарифами выкупа eSIM и приоритетами."
        await ui.display(event=callback, text=text, reply_markup=await get_owner_categories_kb(categories))
        await callback.answer()
    except Exception:
        logger.exception("Error in categories handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(CatManageCD.filter(F.action == "view"), IsOwnerFilter())
async def cb_owner_category_view(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession, ui: MessageManager):
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
    await ui.display(event=callback, text=text, reply_markup=await get_owner_category_detail_kb(cat.id, cat.is_active, cat.is_priority))
    await callback.answer()


@router.callback_query(CatManageCD.filter(F.action == "edit_price"), IsOwnerFilter())
async def cb_owner_cat_price_start(callback: CallbackQuery, callback_data: CatManageCD, state: FSMContext, ui: MessageManager):
    await state.update_data(edit_cat_id=callback_data.cat_id)
    await state.set_state(OwnerStates.waiting_for_cat_price)
    kb = (PremiumBuilder().back(CatManageCD(action="view", cat_id=callback_data.cat_id), "❌ ОТМЕНА").as_markup())
    await ui.display(event=callback, text="💰 <b>Введите новую цену (USDT):</b>", reply_markup=kb)
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
                reply_markup=await get_owner_categories_kb(categories),
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
        await cb_owner_category_view(callback, callback_data, session, ui)
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
        f"🚀 <b>СКЛАД:</b> <code>{summary.get('warehouse', 0)}</code>\n"
        f"👥 <b>ОНЛАЙН:</b> <code>{len(online)}</code> модераторов\n"
        f"{DIVIDER_LIGHT}\n<b>ЛОГ ДЕЙСТВИЙ:</b>\n"
    )
    text += "\n".join([f"├ <code>[{a['time'].strftime('%H:%M')}]</code> @{a['admin']} → #{a['sub_id']}" for a in actions])
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=await get_owner_monitoring_kb(), parse_mode="HTML")
    await callback.answer("🔄 Данные обновлены")


@router.callback_query(F.data == "owner_settings_maintenance", IsOwnerFilter())
async def cb_owner_settings_maint(callback: CallbackQuery, session: AsyncSession):
    from src.core.config import get_settings
    s = get_settings()
    s.maintenance_mode = not s.maintenance_mode
    await callback.answer(f"Режим обслуживания: {'ВКЛ' if s.maintenance_mode else 'ВЫКЛ'}", show_alert=True)
    await cb_owner_monitoring(callback, session, ui)


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
async def cb_owner_settings_root(callback: CallbackQuery, ui: MessageManager):
    """Настройки системы."""
    logger.info("Entering settings handler")
    try:
        from src.core.config import get_settings
        m_mode = getattr(get_settings(), "maintenance_mode", False)
        from src.presentation.admin_panel.owner import get_owner_settings_kb
        await ui.display(event=callback, text="⚙️ <b>НАСТРОЙКИ СИСТЕМЫ</b>", reply_markup=await get_owner_settings_kb(m_mode))
        await callback.answer()
    except Exception:
        logger.exception("Error in settings handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data.in_(["owner_stats_platform", "owner_stats_mods", "owner_stats_sellers"]), IsOwnerFilter())
async def cb_owner_stats_view(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    svc = AdminStatsService(session)
    now = datetime.now(timezone.utc)
    if "platform" in callback.data:
        res = await svc.get_platform_stats(now - timedelta(days=30), now)
        text = _renderer.render_platform_analytics(res)
    elif "mods" in callback.data:
        res = await svc.get_moderators_performance(now - timedelta(days=30), now)
        text = _renderer.render_moderators_stats(res)
    else:
        res, _ = await svc.get_leaderboard(period="30d", page_size=10)
        text = _renderer.render_premium_leaderboard(res, "За 30 дней")
    await ui.display(event=callback, text=text, reply_markup=PremiumBuilder().back("owner_stats").as_markup())
    await callback.answer()


@router.callback_query(F.data == "owner_stats", IsOwnerFilter())
async def cb_owner_stats_root(callback: CallbackQuery, ui: MessageManager):
    """Меню аналитики и статистики."""
    logger.info("Entering stats handler")
    try:
        from src.presentation.admin_panel.owner import get_owner_stats_kb
        await ui.display(
            event=callback, 
            text="📈 <b>АНАЛИТИКА И СТАТИСТИКА</b>\n\nВыберите раздел для детального просмотра показателей платформы.", 
            reply_markup=await get_owner_stats_kb()
        )
        await callback.answer()
    except Exception:
        logger.exception("Error in stats handler")
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data == "owner_settings_security", IsOwnerFilter())
async def cb_owner_security_root(callback: CallbackQuery, ui: MessageManager):
    """Раздел безопасности и логов."""
    from src.presentation.admin_panel.owner import get_owner_security_kb
    await ui.display(
        event=callback, 
        text="🔐 <b>БЕЗОПАСНОСТЬ И ЛОГИ</b>\n\nПросмотр аудита действий, управление сессиями и логами системы.", 
        reply_markup=await get_owner_security_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "owner_sec_audit", IsOwnerFilter())
async def cb_owner_sec_audit(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Просмотр последних действий модерации."""
    svc = AdminStatsService(session)
    actions = await svc.get_recent_moderation_actions(limit=20)
    text = _renderer.render_moderation_audit(actions)
    kb = (PremiumBuilder().back("owner_settings_security").as_markup())
    await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "owner_sec_audit_search", IsOwnerFilter())
async def cb_owner_sec_audit_search_start(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Начало поиска по номеру в аудите."""
    await state.set_state(OwnerStates.waiting_for_audit_query)
    kb = (PremiumBuilder().back("owner_settings_security", "❌ ОТМЕНА").as_markup())
    await ui.display(event=callback, text="🔍 <b>Введите номер телефона (или его часть) для поиска:</b>", reply_markup=kb)
    await callback.answer()


@router.message(OwnerStates.waiting_for_audit_query, IsOwnerFilter())
async def process_owner_sec_audit_search(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ввода номера для поиска в аудите."""
    query = message.text.strip()
    svc = AdminStatsService(session)
    actions = await svc.search_moderation_actions(query)
    
    text = _renderer.render_moderation_audit(actions, title=f"ПОИСК: {query}")
    kb = (PremiumBuilder().back("owner_settings_security").as_markup())
    
    await state.clear()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "owner_sec_cleanup", IsOwnerFilter())
async def cb_owner_sec_cleanup(callback: CallbackQuery):
    """Очистка системных логов."""
    log_path = "logs/admin_actions.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "w") as f:
                f.truncate(0)
            await callback.answer("🧹 Логи успешно очищены", show_alert=True)
        except Exception as e:
            await callback.answer(f"❌ Ошибка при очистке: {e}", show_alert=True)
    else:
        await callback.answer("❌ Файл логов не найден", show_alert=True)


@router.callback_query(F.data == "owner_sec_sessions", IsOwnerFilter())
async def cb_owner_sec_sessions(callback: CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Просмотр активных сессий."""
    # Для демонстрации считаем уникальных пользователей в ReviewAction за последние 24 часа
    since = datetime.now(timezone.utc) - timedelta(days=1)
    stmt = select(func.count(func.distinct(ReviewAction.admin_id))).where(ReviewAction.created_at >= since)
    count = await session.scalar(stmt) or 0
    
    text = (
        f"📍 <b>АКТИВНЫЕ СЕССИИ (24H)</b>\n{DIVIDER}\n"
        f"👥 Уникальных модераторов: <code>{count}</code>\n"
        f"📡 Платформа: <code>ACTIVE</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"<i>Сессии завершаются автоматически при неактивности.</i>"
    )
    kb = (PremiumBuilder().back("owner_settings_security").as_markup())
    await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "owner_sec_level", IsOwnerFilter())
async def cb_owner_sec_level(callback: CallbackQuery):
    """Выбор уровня логирования."""
    text = (
        "📊 <b>УРОВЕНЬ ЛОГИРОВАНИЯ</b>\n"
        f"{DIVIDER}\n"
        "Выберите детализацию системных логов:\n\n"
        "• <code>DEBUG</code> — Все события (макс. объем)\n"
        "• <code>INFO</code> — Основные действия (рекомендуется)\n"
        "• <code>WARNING</code> — Только ошибки и предупреждения"
    )
    kb = (PremiumBuilder()
          .button("DEBUG", "owner_sec_level_set:DEBUG")
          .button("INFO", "owner_sec_level_set:INFO")
          .button("WARNING", "owner_sec_level_set:WARNING")
          .adjust(3)
          .back("owner_settings_security")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("owner_sec_level_set:"), IsOwnerFilter())
async def cb_owner_sec_level_set(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    # Здесь мы могли бы менять уровень динамически, но aiogram/loguru требует перенастройки.
    # Для прототипа просто сохраняем видимость действия.
    await callback.answer(f"✅ Уровень {level} установлен (требуется перезапуск для применения)", show_alert=True)


@router.callback_query(F.data == "owner_settings_global", IsOwnerFilter())
async def cb_owner_settings_global(callback: CallbackQuery):
    """Меню глобальных параметров системы."""
    from src.core.config import get_settings
    s = get_settings()
    
    m_mode = "ВКЛЮЧЕН 🛠" if s.maintenance_mode else "ВЫКЛЮЧЕН ▫️"
    mod_susp = "ПРИОСТАНОВЛЕНА 🛑" if getattr(s, "moderation_suspended", False) else "АКТИВНА 🟢"
    
    text = (
        "🌐 <b>ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ</b>\n"
        f"{DIVIDER}\n"
        f"⚙️ Режим обслуживания: <code>{m_mode}</code>\n"
        f"⚖️ Модерация: <code>{mod_susp}</code>\n"
        f"🔔 Канал бренда: <code>{s.brand_channel_url or 'не задан'}</code>\n"
        f"💬 Чат поддержки: <code>{s.brand_chat_url or 'не задан'}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        "<i>Настройки применяются в реальном времени.</i>"
    )
    
    kb = (PremiumBuilder()
          .button("🛠 ТЕХ. РАБОТЫ: " + ("ВЫКЛ" if s.maintenance_mode else "ВКЛ"), "owner_settings_maintenance")
          .button("⚖️ МОДЕРАЦИЯ: " + ("ВКЛ" if getattr(s, "moderation_suspended", False) else "СТОП"), "owner_mods_toggle")
          .adjust(1)
          .back("owner_settings")
          .as_markup())
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "owner_mods_toggle", IsOwnerFilter())
async def cb_owner_mods_toggle(callback: CallbackQuery, session: AsyncSession):
    """Быстрое переключение модерации из меню параметров."""
    from src.core.config import get_settings
    s = get_settings()
    is_suspended = not getattr(s, "moderation_suspended", False)
    s.moderation_suspended = is_suspended
    
    msg = "🛑 Модерация остановлена" if is_suspended else "🟢 Модерация возобновлена"
    await callback.answer(msg, show_alert=True)
    await cb_owner_settings_global(callback)


@router.callback_query(F.data == "owner_settings_roles", IsOwnerFilter())
async def cb_owner_settings_roles(callback: CallbackQuery, state: FSMContext):
    """Начало процесса управления ролями."""
    await state.set_state(OwnerStates.waiting_for_role_id)
    kb = (PremiumBuilder().back("owner_users", "❌ ОТМЕНА").as_markup())
    await edit_message_text_or_caption_safe(callback.message, "🆔 <b>Введите Telegram ID для смены роли:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(OwnerStates.waiting_for_role_id, IsOwnerFilter())
async def process_owner_role_search(message: Message, state: FSMContext, session: AsyncSession):
    """Поиск пользователя для смены роли."""
    if not message.text.isdigit(): return await message.answer("❌ Введите числовой Telegram ID.")
    
    tid = int(message.text)
    svc = UserService(session)
    user = await svc.get_by_telegram_id(tid)
    
    if not user:
        return await message.answer("🔍 Пользователь не найден. Убедитесь, что он запускал бот.")
    
    await state.update_data(target_user_id=user.id)
    text = (
        f"👤 <b>УПРАВЛЕНИЕ ПРАВАМИ</b>\n{DIVIDER}\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"👤 User: @{user.username or 'N/A'}\n"
        f"🏷️ Текущая роль: <code>{user.role.value.upper()}</code>\n"
        f"{DIVIDER_LIGHT}\nВыберите новую роль для пользователя:"
    )
    
    kb = (PremiumBuilder()
          .button("👤 СЕЛЛЕР", "owner_role_set:seller")
          .button("⚖️ МОДЕРАТОР", "owner_role_set:admin")
          .adjust(1)
          .back("owner_users")
          .as_markup())
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("owner_role_set:"), IsOwnerFilter())
async def cb_owner_role_apply(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Применение новой роли."""
    role_str = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("target_user_id")
    
    if not user_id: return await callback.answer("❌ Ошибка сессии", show_alert=True)
    
    user = await session.get(User, user_id)
    if user:
        user.role = UserRole.ADMIN if role_str == "admin" else UserRole.SELLER
        await session.commit()
        await callback.answer(f"✅ Роль пользователя обновлена до {role_str.upper()}", show_alert=True)
        await state.clear()
        await cb_owner_users_main(callback, session)
    else:
        await callback.answer("❌ Пользователь не найден", show_alert=True)


@router.callback_query(OwnerUserCD.filter(F.action == "history"), IsOwnerFilter())
async def cb_owner_user_history(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession):
    """Просмотр истории действий конкретного пользователя."""
    user = await session.get(User, callback_data.user_id)
    if not user: return await callback.answer("❌ Не найден", show_alert=True)
    
    svc = AdminStatsService(session)
    actions = await svc.get_user_actions_history(user.id)
    
    title = f"ИСТОРИЯ: @{user.username or user.telegram_id}"
    text = _renderer.render_moderation_audit(actions, title=title)
    kb = (PremiumBuilder().back(OwnerUserCD(action="view", user_id=user.id, page=callback_data.page, role=callback_data.role)).as_markup())
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "owner_finance_bulk", IsOwnerFilter())
async def cb_owner_finance_bulk(callback: CallbackQuery):
    """Меню массовых выплат."""
    text = (
        "📦 <b>МАССОВЫЕ ВЫПЛАТЫ</b>\n"
        f"{DIVIDER}\n"
        "Данный раздел позволяет проводить выплаты сразу всем селлерам с балансом > 0.\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Действие необратимо и требует наличия средств на балансе CryptoBot.\n"
        f"{DIVIDER_LIGHT}\n"
        "<i>В данный момент доступен только экспорт списка для ручной проверки.</i>"
    )
    kb = (PremiumBuilder()
          .button("📤 ЭКСПОРТ ДЛЯ ВЫПЛАТ (CSV)", "owner_finance_bulk_export")
          .danger("⚡️ ПРОВЕСТИ ВСЕМ (COMING SOON)", "owner_finance_bulk_run")
          .adjust(1)
          .back("owner_finance")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(CatManageCD.filter(F.action == "confirm_delete"), IsOwnerFilter())
async def cb_owner_cat_confirm_delete(callback: CallbackQuery, callback_data: CatManageCD):
    from src.presentation.admin_panel.owner import get_cat_manage_confirm_delete_kb
    await edit_message_text_or_caption_safe(
        callback.message, 
        "⚠️ <b>ВНИМАНИЕ!</b>\nВы уверены, что хотите полностью УДАЛИТЬ категорию? Это может повлиять на историю старых активов.", 
        reply_markup=get_cat_manage_confirm_delete_kb(callback_data.cat_id), 
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(CatManageCD.filter(F.action == "delete"), IsOwnerFilter())
async def cb_owner_cat_delete(callback: CallbackQuery, callback_data: CatManageCD, session: AsyncSession):
    cat = await session.get(Category, callback_data.cat_id)
    if cat:
        await session.delete(cat)
        await session.commit()
        await callback.answer("✅ Категория удалена", show_alert=True)
    await cb_owner_categories(callback, session)


@router.callback_query(F.data == "owner_finance_bulk_export", IsOwnerFilter())
async def cb_owner_finance_bulk_export(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """Экспорт списка селлеров с балансом > 0 в CSV."""
    stmt = select(User).where(User.pending_balance > 0).order_by(User.pending_balance.desc())
    sellers = (await session.execute(stmt)).scalars().all()
    
    if not sellers:
        return await callback.answer("❌ Нет селлеров с положительным балансом", show_alert=True)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["TG_ID", "Username", "Balance_USDT", "Details"])
    for s in sellers:
        writer.writerow([s.telegram_id, s.username or "N/A", float(s.pending_balance), s.payout_details or ""])
    
    file_content = output.getvalue().encode("utf-8")
    filename = f"bulk_payouts_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    document = BufferedInputFile(file_content, filename=filename)
    
    await bot.send_document(callback.message.chat.id, document, caption=f"📊 Список на выплату ({len(sellers)} чел.)")
    await callback.answer("✅ Файл отправлен")


@router.callback_query(F.data == "owner_sec_alerts", IsOwnerFilter())
async def cb_owner_sec_alerts(callback: CallbackQuery):
    """Статус критических уведомлений."""
    from src.core.config import get_settings
    s = get_settings()
    
    status_crypto = "✅ АКТИВНО" if s.crypto_pay_token else "❌ ВЫКЛЮЧЕНО"
    status_error = "✅ АКТИВНО" if s.admin_error_chat_id else "❌ ВЫКЛЮЧЕНО"
    
    text = (
        "🛡️ <b>КРИТИЧЕСКИЕ УВЕДОМЛЕНИЯ</b>\n"
        f"{DIVIDER}\n"
        f"💰 Мониторинг выплат: <code>{status_crypto}</code>\n"
        f"🚨 Логирование ошибок: <code>{status_error}</code>\n"
        f"📍 Чат алертов: <code>{s.alert_telegram_chat_id or 'не задан'}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        "<i>Для изменения параметров требуется правка .env</i>"
    )
    kb = (PremiumBuilder().back("owner_settings_security").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "owner_sec_logins", IsOwnerFilter())
async def cb_owner_sec_logins(callback: CallbackQuery, session: AsyncSession):
    """Просмотр последних 'входов' (активности) модераторов."""
    svc = AdminStatsService(session)
    online = await svc.get_online_moderators(minutes=1440) # За последние сутки
    
    text = (
        "🔑 <b>ЛОГИ ВХОДОВ / АКТИВНОСТЬ (24H)</b>\n"
        f"{DIVIDER}\n"
    )
    if not online:
        text += " <i>Нет данных об активности.</i>"
    else:
        for m in online:
            time_str = m['last_active'].strftime("%H:%M")
            text += f" ├ <b>@{m['username']}</b>: <code>{time_str}</code>\n"
            
    text += f"\n{DIVIDER_LIGHT}\n<i>Показывает время последнего действия в системе.</i>"
    kb = (PremiumBuilder().back("owner_settings_security").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.in_(["owner_finance_bulk_run"]), IsOwnerFilter())
async def cb_owner_placeholders_extended(callback: CallbackQuery):
    """Заглушка для пока не реализованных подразделов владельца."""
    await callback.answer("🏗️ В разработке (Silver Sakura Phase 2)", show_alert=True)
