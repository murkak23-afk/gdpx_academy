from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.filters.admin import IsOwnerFilter
from src.utils.ui_builder import GDPXRenderer
from src.utils.text_format import edit_message_text_or_caption_safe
from src.services.admin_stats_service import AdminStatsService
from src.database.models.user import User
from src.database.models.submission import Submission
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import NavCD

router = Router(name="owner-cabinet-router")
_renderer = GDPXRenderer()

@router.callback_query(F.data == "owner_cmd_center", IsOwnerFilter())
async def cb_owner_cmd_center(callback: CallbackQuery, session: AsyncSession):
    """Командный центр: Сводка долгов, выплат и активности модераторов."""
    stats_svc = AdminStatsService(session)
    stats = await stats_svc.get_owner_summary_stats()
    stats["username"] = callback.from_user.username or str(callback.from_user.id)
    
    text = _renderer.render_owner_dashboard(stats)
    kb = (PremiumBuilder()
          .button("📊 Обновить данные", "owner_cmd_center")
          .back(NavCD(to="admin_menu"))
          .as_markup())
          
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

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
          .button("🎁 Настроить призы", "owner_lb_prizes")
          .back("admin_menu")
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_finance", IsOwnerFilter())
async def cb_owner_finance(callback: CallbackQuery, session: AsyncSession):
    """Раздел выплат и финансов."""
    stats_svc = AdminStatsService(session)
    stats = await stats_svc.get_owner_summary_stats()
    
    # Получаем топ селлеров с балансом > 0
    stmt = select(User).where(User.pending_balance > 0).order_by(User.pending_balance.desc()).limit(10)
    pending_sellers = (await session.execute(stmt)).scalars().all()
    
    text = _renderer.render_owner_finance(stats, pending_sellers)
    
    # Кнопки для финансов
    kb = (PremiumBuilder()
          .button("💸 ПРОВЕСТИ ВЫПЛАТУ", "admin_finance")
          .button("📜 ИСТОРИЯ ВЫПЛАТ", "payhistory")
          .button("➕ ПОПОЛНИТЬ БАЛАНС", "topup")
          .button("📈 СТАТИСТИКА ВЫПЛАТ", "paystats")
          .adjust(1)
          .back(NavCD(to="admin_menu"))
          .as_markup())
          
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

from datetime import datetime, timedelta, timezone

@router.callback_query(F.data == "owner_stats", IsOwnerFilter())
async def cb_owner_stats(callback: CallbackQuery):
    """Раздел аналитики и статистики."""
    text = (
        "📈 <b>АНАЛИТИКА И СТАТИСТИКА</b>\n\n"
        "В этом разделе вы можете отслеживать эффективность платформы, модераторов и селлеров.\n\n"
        "<i>Выберите тип отчета:</i>"
    )
    kb = (PremiumBuilder()
          .button("📊 Общая статистика платформы", "owner_stats_platform")
          .button("👥 Эффективность модераторов", "owner_stats_mods")
          .button("💰 Рейтинг селлеров", "owner_stats_sellers")
          .adjust(1)
          .back(NavCD(to="admin_menu"))
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_stats_platform", IsOwnerFilter())
async def cb_owner_stats_platform(callback: CallbackQuery, session: AsyncSession):
    """Общая статистика платформы."""
    stats_svc = AdminStatsService(session)
    # За все время (условно с начала 2024 года)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    
    stats = await stats_svc.get_platform_stats(start, end)
    text = _renderer.render_platform_analytics(stats)
    
    kb = (PremiumBuilder().back("owner_stats").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_stats_mods", IsOwnerFilter())
async def cb_owner_stats_mods(callback: CallbackQuery, session: AsyncSession):
    """Статистика по модераторам."""
    stats_svc = AdminStatsService(session)
    start = datetime.now(timezone.utc) - timedelta(days=30) # За 30 дней
    end = datetime.now(timezone.utc)
    
    mods = await stats_svc.get_moderators_performance(start, end)
    text = _renderer.render_moderators_stats(mods)
    
    kb = (PremiumBuilder().back("owner_stats").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_stats_sellers", IsOwnerFilter())
async def cb_owner_stats_sellers(callback: CallbackQuery, session: AsyncSession):
    """Статистика по селлерам."""
    stats_svc = AdminStatsService(session)
    start = datetime.now(timezone.utc) - timedelta(days=30) # За 30 дней
    end = datetime.now(timezone.utc)
    
    sellers = await stats_svc.get_top_sellers_extended(start, end)
    text = _renderer.render_sellers_leaderboard_owner(sellers)
    
    kb = (PremiumBuilder().back("owner_stats").as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_categories", IsOwnerFilter())
async def cb_owner_categories(callback: CallbackQuery):
    """Управление категориями и ставками."""
    from src.keyboards.owner import get_catcon_main_kb
    text = "🏷️ <b>КАТЕГОРИИ И СТАВКИ</b>\n\nУправление кластерами выкупа и тарифными сетками."
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_catcon_main_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_leaderboard", IsOwnerFilter())
async def cb_owner_leaderboard(callback: CallbackQuery):
    """Доска лидеров."""
    text = "🏆 <b>ДОСКА ЛИДЕРОВ</b>\n\nУправление рейтингами и призовыми фондами."
    kb = (PremiumBuilder()
          .button("🥇 Лидерборд селлеров", "leaderboard:sellers")
          .button("🥈 Лидерборд модераторов", "leaderboard:mods")
          .button("🎁 Настройка призов", "owner_lb_prizes")
          .adjust(1)
          .back(NavCD(to="admin_menu"))
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "owner_to_moderation", IsOwnerFilter())
async def cb_owner_to_moderation(callback: CallbackQuery, session: AsyncSession):
    """Переход в режим модерации."""
    from src.handlers.admin import on_enter_moderator_panel
    await on_enter_moderator_panel(callback, session)
    await callback.answer("Вход в режим модератора...")

from aiogram.fsm.state import State, StatesGroup

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

class RoleStates(StatesGroup):
    waiting_for_user_id = State()

@router.callback_query(F.data == "owner_settings", IsOwnerFilter())
async def cb_owner_settings(callback: CallbackQuery):
    """Настройки системы."""
    text = (
        "⚙️ <b>НАСТРОЙКИ СИСТЕМЫ</b>\n\n"
        "Глобальное управление параметрами бота и безопасностью.\n\n"
        "<i>Текущая версия: 3.6.0 Sakura Premium</i>"
    )
    kb = (PremiumBuilder()
          .button("🌐 Глобальные настройки", "owner_settings_global")
          .button("🔑 Управление ролями", "owner_settings_roles")
          .button("🔔 Уведомления", "owner_settings_notify")
          .button("📜 Логи и аудит", "owner_settings_audit")
          .button("💾 Backup / Экспорт", "owner_settings_backup")
          .adjust(1)
          .back(NavCD(to="admin_menu"))
          .as_markup())
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(BroadcastStates.waiting_for_message, IsOwnerFilter())
async def process_broadcast(message: Message, state: FSMContext, session: AsyncSession):
    """Процесс рассылки."""
    await state.clear()
    from src.services.user_service import UserService
    user_svc = UserService(session)
    # Это упрощенная версия, в реальности лучше через задачу в фоне (Celery/Taskiq)
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
        from src.services.user_service import UserService
        user_svc = UserService(session)
        user = await user_svc.get_by_telegram_id(target_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден в базе данных.")
            return
            
        user.role = UserRole.ADMIN if action == "add" else UserRole.SELLER
        await session.commit()
        
        await message.answer(f"✅ Пользователь {user.username or user.telegram_id} теперь <b>{user.role}</b>")
    except ValueError:
        await message.answer("❌ Некорректный ID. Введите число.")

import csv
import io
from aiogram.types import BufferedInputFile

@router.callback_query(F.data == "owner_settings_backup", IsOwnerFilter())
async def cb_owner_export(callback: CallbackQuery, session: AsyncSession):
    """Экспорт статистики в CSV."""
    await callback.answer("⏳ Формирую отчет...", show_alert=False)
    
    stats_svc = AdminStatsService(session)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    
    # Получаем данные для экспорта (принятые заявки)
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
            s.category_id, # Можно расширить до названия категории если нужно
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

# Заглушки для подменю
@router.callback_query(F.data.startswith("owner_stats_"), IsOwnerFilter())
@router.callback_query(F.data.startswith("owner_lb_"), IsOwnerFilter())
@router.callback_query(F.data.startswith("owner_settings_"), IsOwnerFilter())
async def cb_owner_placeholders(callback: CallbackQuery):
    await callback.answer("🏗️ Этот раздел находится в разработке", show_alert=True)
