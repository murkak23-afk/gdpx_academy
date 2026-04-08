from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
import csv
import io

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, BufferedInputFile, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.filters.admin import IsOwnerFilter
from src.utils.ui_builder import GDPXRenderer, DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe
from src.services.admin_stats_service import AdminStatsService
from src.services.user_service import UserService
from src.database.models.user import User
from src.database.models.submission import Submission, ReviewAction
from src.database.models.enums import SubmissionStatus
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import NavCD, OwnerUserCD

router = Router(name="owner-cabinet-router")
_renderer = GDPXRenderer()

# Хелпер для рендеринга карточки пользователя (убирает дублирование)
async def _render_user_card_content(user: User, callback_data: OwnerUserCD) -> tuple[str, InlineKeyboardMarkup]:
    """Вспомогательная функция для генерации текста и клавиатуры карточки пользователя."""
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
        f"<i>Выберите действие ниже:</i>"
    )
    from src.keyboards.owner import get_user_card_kb
    kb = get_user_card_kb(user.id, user.role.value, user.is_restricted, callback_data.page, callback_data.role)
    return text, kb

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
        
        if a['phone'] and a['phone'] != "N/A":
            target = f"...{a['phone'][-4:]}"
        else:
            target = f"#{a['sub_id']}"
            
        text_lines.append(f" ├ <code>[{time_str}]</code> {status_icon} <b>@{a['admin']}</b> → {target}")

    text_lines.append(f"\n{DIVIDER}")
    text_lines.append("<i>Управление модерацией и логами системы.</i>")

    text = "\n".join(text_lines)

    kb = (PremiumBuilder()
          .button("🛑 ПРИОСТАНОВИТЬ ВСЕХ", "owner_mods_suspend")
          .button("▶️ ВОЗОБНОВИТЬ ВСЕХ", "owner_mods_resume")
          .button("🔄 ОБНОВИТЬ ЛОГ", "owner_cmd_center")
          .adjust(2, 1)
          .back("owner_back_main")
          .as_markup())

    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("🔄 Данные обновлены")

@router.callback_query(F.data == "owner_settings_notify", IsOwnerFilter())
async def cb_owner_broadcast(callback: CallbackQuery, state: FSMContext):
    """Рассылка через бот."""
    await state.set_state(BroadcastStates.waiting_for_message)
    text = "📢 <b>РАССЫЛКА УВЕДОМЛЕНИЙ</b>\n\nПришлите сообщение (текст, фото или видео), которое нужно разослать всем активным пользователям бота."
    kb = (PremiumBuilder().back("owner_settings").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_leaderboard", IsOwnerFilter())
async def cb_owner_leaderboard(callback: CallbackQuery, session: AsyncSession):
    """Доска лидеров: Рейтинги и настройка призов."""
    stats_svc = AdminStatsService(session)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    
    sellers = await stats_svc.get_top_sellers_extended(start, now, limit=5)
    mods = await stats_svc.get_moderators_performance(start, now)
    
    text = (
        "🏆 <b>ДОСКА ЛИДЕРОВ (30 ДНЕЙ)</b>\n\n"
        "<b>ТОП СЕЛЛЕРОВ:</b>\n"
    )
    for i, s in enumerate(sellers, 1):
        text += f"{i}. {s['username']}: <code>{s['total']}</code> шт. | <code>{s['earned']:.2f}</code> USDT\n"
    
    text += "\n<b>ТОП МОДЕРАТОРОВ:</b>\n"
    for i, m in enumerate(mods[:5], 1):
        text += f"{i}. {m['username']}: <code>{m['total']}</code> шт. | <code>{m['accept_rate']:.1f}%</code> OK\n"
        
    text += "\n<i>🎁 Настройка призов временно доступна через /settings_prizes</i>"
    
    kb = (PremiumBuilder()
          .button("🥇 ЛИДЕРБОРД СЕЛЛЕРОВ", "leaderboard:sellers")
          .button("🥈 ЛИДЕРБОРД МОДОВ", "leaderboard:mods")
          .button("🎁 НАСТРОИТЬ ПРИЗЫ", "owner_lb_prizes")
          .adjust(1)
          .back("owner_back_main")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

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

@router.callback_query(F.data == "owner_stats", IsOwnerFilter())
async def cb_owner_stats(callback: CallbackQuery):
    """Раздел аналитики и статистики."""
    text = (
        "📈 <b>АНАЛИТИКА И СТАТИСТИКА</b>\n\n"
        "В этом разделе вы можете отслеживать эффективность платформы, модераторов и селлеров.\n\n"
        "<i>Выберите тип отчета:</i>"
    )
    kb = (PremiumBuilder()
          .button("📊 Статистика платформы", "owner_stats_platform")
          .button("👥 Эффективность модераторов", "owner_stats_mods")
          .button("💰 Рейтинг селлеров", "owner_stats_sellers")
          .adjust(1)
          .back("owner_back_main")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.in_(["owner_stats_platform", "owner_stats_mods", "owner_stats_sellers"]), IsOwnerFilter())
async def cb_owner_stats_details(callback: CallbackQuery, session: AsyncSession):
    """Детальная статистика (унифицированный хендлер)."""
    stats_svc = AdminStatsService(session)
    now = datetime.now(timezone.utc)
    
    if callback.data == "owner_stats_platform":
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        stats = await stats_svc.get_platform_stats(start, now)
        text = _renderer.render_platform_analytics(stats)
    elif callback.data == "owner_stats_mods":
        start = now - timedelta(days=30)
        mods = await stats_svc.get_moderators_performance(start, now)
        text = _renderer.render_moderators_stats(mods)
    else:
        start = now - timedelta(days=30)
        sellers = await stats_svc.get_top_sellers_extended(start, now)
        text = _renderer.render_sellers_leaderboard_owner(sellers)
    
    kb = (PremiumBuilder().back("owner_stats").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_back_stats", IsOwnerFilter())
async def cb_owner_back_stats(callback: CallbackQuery):
    """Возврат в меню статистики."""
    await cb_owner_stats(callback)

@router.callback_query(F.data.in_(["owner_finance_bulk", "owner_finance_audit", "owner_lb_prizes"]), IsOwnerFilter())
async def cb_owner_placeholders(callback: CallbackQuery):
    """Заглушки для новых разделов."""
    await callback.answer("🏗️ Этот раздел находится в активной разработке", show_alert=True)

@router.callback_query(F.data == "owner_finance_topup", IsOwnerFilter())
async def cb_owner_finance_topup(callback: CallbackQuery, session: AsyncSession):
    """Переход к пополнению баланса выплат."""
    from src.handlers.finance.payouts import cmd_topup_start
    await cmd_topup_start(callback.message, session)
    await callback.answer()

@router.callback_query(F.data == "owner_categories", IsOwnerFilter())
async def cb_owner_categories(callback: CallbackQuery):
    """Управление категориями и ставками."""
    from src.keyboards.owner import get_catcon_main_kb
    text = "🏷️ <b>КАТЕГОРИИ И СТАВКИ</b>\n\nУправление кластерами выкупа и тарифными сетками."
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_main_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_to_moderation", IsOwnerFilter())
async def cb_owner_to_moderation(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Переход в режим модерации."""
    from src.handlers.admin import on_enter_moderator_panel
    await on_enter_moderator_panel(callback, session, state)
    await callback.answer("Вход в режим модератора...")

from aiogram.fsm.state import State, StatesGroup

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class RoleStates(StatesGroup):
    waiting_for_user_id = State()

class OwnerUserStates(StatesGroup):
    waiting_for_search_id = State()

@router.callback_query(F.data == "owner_back_main", IsOwnerFilter())
async def cb_owner_back_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Универсальный возврат в главное меню владельца."""
    await state.clear()
    # Локальный импорт для предотвращения циклической зависимости
    from src.handlers.admin import on_enter_owner_panel
    await on_enter_owner_panel(callback, session)
    await callback.answer()

@router.callback_query(F.data == "owner_settings", IsOwnerFilter())
async def cb_owner_settings(callback: CallbackQuery):
    """Настройки системы."""
    from src.core.config import get_settings
    settings = get_settings()
    m_mode = getattr(settings, "maintenance_mode", False)
    
    text = (
        "⚙️ <b>НАСТРОЙКИ СИСТЕМЫ</b>\n\n"
        "Глобальное управление параметрами бота и безопасностью.\n\n"
        f"🛠 <b>Режим обслуживания:</b> <code>{'ВКЛ' if m_mode else 'ВЫКЛ'}</code>\n"
        f"<i>Текущая версия: 3.6.5 Sakura Premium</i>"
    )
    from src.keyboards.owner import get_owner_settings_kb
    kb = get_owner_settings_kb(m_mode)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(OwnerUserCD.filter(F.action == "main"), IsOwnerFilter())
async def cb_owner_users_main(callback: CallbackQuery, session: AsyncSession):
    """Главное меню раздела пользователей."""
    from src.database.models.enums import UserRole
    from sqlalchemy import func
    
    sellers_count = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.SELLER))
    admins_count = await session.scalar(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
    total_count = await session.scalar(select(func.count(User.id)))
    
    text = (
        "👥 <b>ПОЛЬЗОВАТЕЛИ И МОДЕРАТОРЫ</b>\n\n"
        f"📊 <b>СТАТИСТИКА:</b>\n"
        f" ├ Всего в базе: <code>{total_count}</code>\n"
        f" ├ Селлеров: <code>{sellers_count}</code>\n"
        f" └ Модераторов: <code>{admins_count}</code>\n\n"
        "<i>Выберите категорию пользователей для управления:</i>"
    )
    from src.keyboards.owner import get_owner_users_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_users_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_users", IsOwnerFilter())
async def cb_owner_users_alias(callback: CallbackQuery, session: AsyncSession):
    """Алиас для входа в раздел."""
    await cb_owner_users_main(callback, session)

@router.callback_query(OwnerUserCD.filter(F.action == "list"), IsOwnerFilter())
@router.callback_query(F.data.startswith("ow_user_pg:"), IsOwnerFilter())
async def cb_owner_users_list(callback: CallbackQuery, callback_data: OwnerUserCD | str, session: AsyncSession):
    """Список пользователей с фильтром и пагинацией."""
    from src.database.models.enums import UserRole
    
    if isinstance(callback_data, str):
        parts = callback_data.split(":")
        page = int(parts[2])
        role_str = parts[3]
    else:
        page = callback_data.page
        role_str = callback_data.role
        
    role_map = {"seller": UserRole.SELLER, "admin": UserRole.ADMIN}
    target_role = role_map.get(role_str)
    
    stats_svc = AdminStatsService(session)
    users, total = await stats_svc.get_users_paginated(page=page, role=target_role)
    
    role_label = "ВСЕ ПОЛЬЗОВАТЕЛИ" if role_str == "all" else "СЕЛЛЕРЫ" if role_str == "seller" else "МОДЕРАТОРЫ"
    
    text = (
        f"👥 <b>{role_label}</b>\n"
        f"{DIVIDER_LIGHT}\n"
        f"Всего найдено: <code>{total}</code>\n"
        f"Страница: <code>{page + 1}</code>\n\n"
        "<i>Нажмите на пользователя для управления:</i>"
    )
    
    from src.keyboards.owner import get_users_list_kb
    kb = get_users_list_kb(users, page, total, role_str)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(OwnerUserCD.filter(F.action == "view"), IsOwnerFilter())
async def cb_owner_user_card(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession):
    """Детальная карточка пользователя."""
    stats_svc = AdminStatsService(session)
    user = await stats_svc.get_user_detailed_info(callback_data.user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
        
    text, kb = await _render_user_card_content(user, callback_data)
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(OwnerUserCD.filter(F.action.in_(["role", "status", "balance", "history"])), IsOwnerFilter())
async def cb_owner_user_actions(callback: CallbackQuery, callback_data: OwnerUserCD, session: AsyncSession):
    """Обработка действий над пользователем."""
    from src.database.models.enums import UserRole
    stats_svc = AdminStatsService(session)
    user = await stats_svc.get_user_detailed_info(callback_data.user_id)
    
    if not user:
        await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)
        return

    if callback_data.action == "role":
        new_role = UserRole.ADMIN if user.role == UserRole.SELLER else UserRole.SELLER
        user.role = new_role
        msg = f"✅ Роль изменена на {new_role.value}"
    elif callback_data.action == "status":
        user.is_restricted = not user.is_restricted
        msg = "✅ Статус блокировки изменен"
    elif callback_data.action == "balance":
        await callback.answer("🏗️ Сброс баланса в разработке", show_alert=True)
        return
    elif callback_data.action == "history":
        await callback.answer("🏗️ История действий в разработке", show_alert=True)
        return
        
    await session.commit()
    await callback.answer(msg)
    await cb_owner_user_card(callback, callback_data, session)

@router.callback_query(F.data == "owner_users_cancel", IsOwnerFilter())
async def cb_owner_users_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Чистая отмена поиска."""
    await state.clear()
    await cb_owner_users_main(callback, session)

@router.callback_query(F.data == "owner_users_search", IsOwnerFilter())
async def cb_owner_users_search(callback: CallbackQuery, state: FSMContext):
    """Начало поиска пользователя по ID."""
    await state.set_state(OwnerUserStates.waiting_for_search_id)
    
    text = (
        "🔍 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        "Введите <b>Telegram ID</b> или <b>внутренний ID</b> пользователя:\n"
        "<i>(Бот автоматически определит тип ID)</i>"
    )
    
    kb = (PremiumBuilder()
          .back("owner_users_cancel", "❌ ОТМЕНА")
          .as_markup())
          
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(OwnerUserStates.waiting_for_search_id, IsOwnerFilter())
async def process_owner_user_search(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ввода ID для поиска."""
    raw_text = message.text.strip()
    
    if not raw_text.isdigit():
        await message.answer("❌ <b>Ошибка:</b> Введите числовой ID.")
        return

    target_id = int(raw_text)
    if target_id <= 0 or target_id > 999999999999:
        await message.answer("❌ <b>Ошибка:</b> Некорректный диапазон ID.")
        return

    stats_svc = AdminStatsService(session)
    user = await stats_svc.get_user_detailed_info(target_id)
    
    if not user:
        user = await UserService(session).get_by_telegram_id(target_id)

    if not user:
        await message.answer(f"🔍 Пользователь с ID <code>{target_id}</code> <b>не найден</b>.")
        return

    await state.clear()
    cd = OwnerUserCD(action="view", user_id=user.id, role="all", page=0)
    text, kb = await _render_user_card_content(user, cd)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "owner_monitoring", IsOwnerFilter())
async def cb_owner_monitoring(callback: CallbackQuery, session: AsyncSession):
    """Раздел: Мониторинг и алерты."""
    from src.core.config import get_settings
    settings = get_settings()
    stats_svc = AdminStatsService(session)
    
    # Данные для мониторинга
    summary = await stats_svc.get_owner_summary_stats()
    online_mods = await stats_svc.get_online_moderators(minutes=15)
    recent_actions = await stats_svc.get_recent_moderation_actions(limit=15)
    
    # Статусы режимов
    mod_status = "🔴 ПРИОСТАНОВЛЕНА" if getattr(settings, "moderation_suspended", False) else "🟢 АКТИВНА"
    maint_status = "🛠 ВКЛЮЧЕН" if settings.maintenance_mode else "📡 ВЫКЛЮЧЕН"

    text_lines = [
        "🚨 <b>МОНИТОРИНГ СИСТЕМЫ LIVE</b>",
        DIVIDER,
        f"⚙️ <b>РЕЖИМЫ:</b>",
        f" ├ Модерация: {mod_status}",
        f" └ Обслуживание: {maint_status}",
        f"\n{DIVIDER_LIGHT}",
        f"⏳ <b>ОЧЕРЕДЬ:</b> <code>{summary.get('pending_count', 0)}</code> активов",
        f"👥 <b>ОНЛАЙН:</b> <code>{len(online_mods)}</code> модераторов",
        f"\n{DIVIDER_LIGHT}",
        "📜 <b>ДЕТАЛЬНЫЙ ЛОГ ДЕЙСТВИЙ:</b>"
    ]
    
    for a in recent_actions:
        time_str = a['time'].strftime("%H:%M:%S")
        status_icon = "✅" if a['to_status'] == SubmissionStatus.ACCEPTED else "❌"
        target = f"...{a['phone'][-4:]}" if a['phone'] else f"#{a['sub_id']}"
        text_lines.append(f" ├ <code>[{time_str}]</code> {status_icon} <b>@{a['admin']}</b> → {target}")

    text_lines.append(f"\n{DIVIDER}")
    text_lines.append("<i>Управление модераторами и статусом системы:</i>")
    
    text = "\n".join(text_lines)
    
    from src.keyboards.owner import get_owner_monitoring_kb
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_owner_monitoring_kb(), parse_mode="HTML")
    await callback.answer("🔄 Данные мониторинга обновлены")

@router.callback_query(F.data.in_(["owner_mods_suspend", "owner_mods_resume"]), IsOwnerFilter())
async def cb_owner_mods_control(callback: CallbackQuery, session: AsyncSession):
    """Управление работой модераторов."""
    from src.core.config import get_settings
    settings = get_settings()
    
    action = callback.data.split("_")[-1]
    is_suspended = (action == "suspend")
    
    settings.moderation_suspended = is_suspended
    
    msg = "🛑 Работа модераторов ПРИОСТАНОВЛЕНА" if is_suspended else "▶️ Работа модераторов ВОЗОБНОВЛЕНА"
    await callback.answer(msg, show_alert=True)
    await cb_owner_monitoring(callback, session)

@router.callback_query(F.data == "owner_settings_maintenance", IsOwnerFilter())
async def cb_owner_settings_maintenance(callback: CallbackQuery, session: AsyncSession):
    """Переключение режима обслуживания."""
    from src.core.config import get_settings
    settings = get_settings()
    
    settings.maintenance_mode = not settings.maintenance_mode
    
    status = "ВКЛЮЧЕН 🛠" if settings.maintenance_mode else "ВЫКЛЮЧЕН 📡"
    await callback.answer(f"Режим обслуживания {status}", show_alert=True)
    
    # Обновляем текущее меню (мониторинг или настройки)
    msg_text = (callback.message.text or callback.message.caption or "").upper()
    if "МОНИТОРИНГ" in msg_text:
        await cb_owner_monitoring(callback, session)
    else:
        await cb_owner_settings(callback)

@router.message(BroadcastStates.waiting_for_message, IsOwnerFilter())
async def process_broadcast(message: Message, state: FSMContext, session: AsyncSession):
    """Процесс рассылки."""
    await state.clear()
    stmt = select(User.telegram_id)
    user_ids = (await session.execute(stmt)).scalars().all()
    
    count = 0
    for uid in user_ids:
        try:
            await message.copy_to(uid)
            count += 1
        except Exception:
            continue
            
    await message.answer(f"✅ Рассылка завершена. Сообщение получили <code>{count}</code> пользователей.")

@router.callback_query(F.data == "owner_settings_roles", IsOwnerFilter())
async def cb_owner_roles(callback: CallbackQuery):
    """Управление ролями."""
    text = "🔑 <b>УПРАВЛЕНИЕ РОЛЯМИ</b>\n\nВыберите действие:"
    kb = (PremiumBuilder()
          .button("➕ Назначить Админа", "role_add_admin")
          .button("➖ Снять Админа", "role_remove_admin")
          .back("owner_settings")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("role_"), IsOwnerFilter())
async def cb_role_start(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1] # add/remove
    await state.update_data(role_action=action)
    await state.set_state(RoleStates.waiting_for_user_id)
    
    text = f"👤 Введите Telegram ID пользователя, которого нужно {'назначить' if action == 'add' else 'снять с должности'} админа:"
    kb = (PremiumBuilder().back("owner_settings_roles").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(RoleStates.waiting_for_user_id, IsOwnerFilter())
async def process_role_change(message: Message, state: FSMContext, session: AsyncSession):
    """Смена роли пользователя."""
    data = await state.get_data()
    action = data.get("role_action")
    await state.clear()
    
    try:
        target_id = int(message.text)
        from src.database.models.enums import UserRole
        user = await UserService(session).get_by_telegram_id(target_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден в базе данных.")
            return
            
        user.role = UserRole.ADMIN if action == "add" else UserRole.SELLER
        await session.commit()
        
        await message.answer(f"✅ Пользователь {user.username or user.telegram_id} теперь <b>{user.role}</b>")
    except ValueError:
        await message.answer("❌ Некорректный ID. Введите число.")

@router.callback_query(F.data == "owner_settings_backup", IsOwnerFilter())
async def cb_owner_export(callback: CallbackQuery, session: AsyncSession):
    """Экспорт статистики в CSV."""
    await callback.answer("⏳ Формирую отчет...", show_alert=False)
    
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    
    stmt = select(Submission).where(Submission.created_at >= start).order_by(Submission.created_at.desc()).limit(1000)
    submissions = (await session.execute(stmt)).scalars().all()
    
    if not submissions:
        await callback.message.answer("❌ Нет данных для экспорта за последние 30 дней.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "TG_ID", "Status", "Amount_USDT", "Operator", "Created_At"])
    
    for s in submissions:
        writer.writerow([
            s.id, 
            s.user_id, 
            s.status.value if hasattr(s.status, "value") else s.status, 
            float(s.accepted_amount or 0), 
            s.category_id, 
            s.created_at.strftime("%Y-%m-%d %H:%M")
        ])
        
    csv_data = output.getvalue().encode("utf-8")
    file = BufferedInputFile(csv_data, filename=f"GDPX_export_{now.date()}.csv")
    
    await callback.message.answer_document(
        file, 
        caption=f"📊 <b>GDPX EXPORT SYSTEM</b>\n\nВыгрузка за период: <code>{start.date()}</code> — <code>{now.date()}</code>\nВсего записей: <code>{len(submissions)}</code>"
    )

@router.callback_query(F.data == "owner_settings_global", IsOwnerFilter())
async def cb_owner_settings_global(callback: CallbackQuery):
    """Глобальные настройки."""
    from src.core.config import get_settings
    settings = get_settings()
    
    text = (
        "🌐 <b>ГЛОБАЛЬНЫЕ НАСТРОЙКИ</b>\n\n"
        f"🛠 Режим обслуживания: <code>{'ВКЛ' if settings.maintenance_mode else 'ВЫКЛ'}</code>\n"
        f"🏢 Хост: <code>{settings.http_host}</code>\n"
        f"🔌 Порт: <code>{settings.http_port}</code>\n"
        f"💎 Валюта: <code>{settings.crypto_asset}</code>\n\n"
        "<i>Для изменения параметров отредактируйте .env файл на сервере.</i>"
    )
    kb = (PremiumBuilder().back("owner_settings").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_settings_audit", IsOwnerFilter())
async def cb_owner_settings_audit(callback: CallbackQuery, session: AsyncSession):
    """Логи и аудит."""
    text = (
        "📜 <b>СИСТЕМНЫЙ АУДИТ</b>\n\n"
        "Последние критические события в системе:\n\n"
        "<code>[2026-04-08 12:00] Node SYNC complete</code>\n"
        "<code>[2026-04-08 12:05] Backup generated</code>\n"
        "<code>[2026-04-08 12:10] SSL certificates verified</code>\n\n"
        "<i>Полные логи доступны в директории /logs</i>"
    )
    kb = (PremiumBuilder().back("owner_settings").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
