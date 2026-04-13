from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.core.logger import logger
from src.database.models.enums import NotificationPreference
from .keyboards import (
    get_favorite_categories_kb,
    get_language_settings_kb,
    get_notification_settings_kb,
    get_seller_payout_history_kb,
    get_seller_profile_kb,
    get_seller_settings_kb,
    get_seller_stats_kb,
)
from src.core.utils.message_manager import MessageManager
from src.presentation.common.factory import SellerMenuCD, SellerNotifCD, SellerSettingsCD, SellerStatsCD
from src.domain.moderation.badge_service import BadgeService
from src.domain.finance.bill_service import BillingService
from src.domain.submission.category_service import CategoryService
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.core.utils.media import media
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT, GDPXRenderer

router = Router(name="seller-profile-premium-router")
_renderer = GDPXRenderer()

# --- ВЫПЛАТЫ (ИСТОРИЯ) ---

@router.callback_query(SellerMenuCD.filter(F.action == "payouts"))
async def show_payout_history(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Отображение истории выплат селлера."""
    try:
        await _render_payout_history(callback, session, ui, period="all")
    except Exception as e:
        logger.exception(f"Error in show_payout_history: {e}")
        await callback.answer("⚠️ Ошибка при загрузке выплат", show_alert=True)

async def _render_payout_history(callback: CallbackQuery, session: AsyncSession, ui: MessageManager, period: str = "all") -> None:
    """Вспомогательная функция для рендеринга истории выплат."""
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        bill_svc = BillingService(session=session)
        
        days_map = {"7": 7, "30": 30, "90": 90, "all": None}
        history, total = await bill_svc.get_payout_history(user_id=user.id, days=days_map.get(period))
        
        banner = media.get("payouts.jpg")
        
        lines = [
            "❖ <b>GDPX // PAYOUT HISTORY</b>",
            f"{DIVIDER}",
            f"👤 <b>АГЕНТ:</b> @{user.username or user.telegram_id}",
            f"📊 <b>ПЕРИОД:</b> <code>{period.upper()}</code>",
            f"{DIVIDER_LIGHT}"
        ]
        
        if not history:
            lines.append("<i>Транзакции за выбранный период не найдены.</i>")
        else:
            for p in history[:15]:
                date_str = p.created_at.strftime("%d.%m.%y %H:%M")
                status_icon = "✅" if p.status == "paid" else "⏳" if p.status == "pending" else "❌"
                lines.append(f"• <code>{date_str}</code> | <b>{p.amount} USDT</b> {status_icon}")
                
        lines.append(f"{DIVIDER_LIGHT}")
        lines.append(f"💰 <b>ВСЕГО ВЫПЛАЧЕНО:</b> <code>{user.total_paid}</code> USDT")
        
        text = "\n".join(lines)
        
        await ui.display(event=callback, text=text, reply_markup=await get_seller_payout_history_kb(period), photo=banner)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in _render_payout_history: {e}")
        raise

@router.callback_query(F.data == "payout_export_csv")
async def export_payouts_csv(callback: CallbackQuery, session: AsyncSession) -> None:
    """Экспорт истории выплат в CSV."""
    try:
        import csv
        import io
        
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        bill_svc = BillingService(session=session)
        history, total = await bill_svc.get_payout_history(user_id=user.id)
        
        if not history:
            return await callback.answer("❌ Нет данных для экспорта", show_alert=True)
            
        await callback.answer("⏳ Формирую CSV...")
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Date", "Amount_USDT", "Status", "Wallet"])
        
        for p in history:
            writer.writerow([
                p.id, 
                p.created_at.strftime("%Y-%m-%d %H:%M"), 
                p.amount, 
                p.status,
                p.wallet_address or "N/A"
            ])
            
        csv_data = output.getvalue().encode("utf-8")
        filename = f"Payouts_{user.telegram_id}_{datetime.now().strftime('%Y%m%d')}.csv"
        
        await callback.message.answer_document(
            document=BufferedInputFile(csv_data, filename=filename),
            caption=f"📋 <b>История ваших выплат</b>\n{DIVIDER}\nПолная выгрузка транзакций в формате CSV.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"Error in export_payouts_csv: {e}")
        await callback.answer("⚠️ Ошибка при экспорте CSV", show_alert=True)

# --- ПРОФИЛЬ И ГЛАВНОЕ МЕНЮ ---

from aiogram.filters import Command


@router.message(Command("profile"))
@router.callback_query(SellerMenuCD.filter(F.action == "profile"))
async def show_profile(event: Message | CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Обновление экрана профиля."""
    try:
        # Очищаем уведомления при входе в профиль
        from src.presentation.common.notifications import clear_notifications
        await clear_notifications(event.from_user.id, event.bot)

        user_id = event.from_user.id
        user = await UserService(session=session).get_by_telegram_id(user_id)
        if not user:
            return

        sub_svc = SubmissionService(session=session)
        dashboard = await sub_svc.get_user_dashboard_stats(user.id)
        
        user.badges = BadgeService.calculate_badges(user, dashboard)
        recent = await sub_svc.list_user_material_by_category_paginated(
            user_id=user.id, category_id=0, page=0, page_size=5, statuses=None
        )
        items = recent[0] if isinstance(recent, tuple) else recent
        
        text = _renderer.render_seller_profile_premium(user=user, stats=dashboard, recent_submissions=items)
        kb = await get_seller_profile_kb()
        banner = media.get("profile.jpg")
        
        await ui.display(event=event, text=text, reply_markup=kb, photo=banner)
        if isinstance(event, CallbackQuery):
            await event.answer()
    except Exception as e:
        logger.exception(f"Error in show_profile: {e}")
        if isinstance(event, CallbackQuery):
            await event.answer("⚠️ Ошибка профиля", show_alert=True)

# --- НАСТРОЙКИ ---

@router.callback_query(SellerMenuCD.filter(F.action == "settings"))
@router.callback_query(SellerSettingsCD.filter(F.action == "main"))
async def show_settings(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        text = _renderer.render_seller_settings(user)
        kb = await get_seller_settings_kb()
        banner = media.get("settings.png")
        await ui.display(event=callback, text=text, reply_markup=kb, photo=banner)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_settings: {e}")
        await callback.answer("⚠️ Ошибка настроек", show_alert=True)

@router.callback_query(SellerSettingsCD.filter(F.action == "alias"))
async def show_personal_data(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Отображение личных данных пользователя."""
    try:
        from src.presentation.common.base import PremiumBuilder
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        sub_svc = SubmissionService(session=session)
        dashboard = await sub_svc.get_user_dashboard_stats(user.id)
        
        text = _renderer.render_personal_data(user, dashboard)
        kb = (PremiumBuilder()
              .back(SellerSettingsCD(action="main"), "В НАСТРОЙКИ")
              .as_markup())
              
        await ui.display(event=callback, text=text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_personal_data: {e}")
        await callback.answer("⚠️ Ошибка личных данных", show_alert=True)

@router.callback_query(SellerSettingsCD.filter(F.action == "incognito"))
async def toggle_incognito(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    user.is_incognito = not user.is_incognito
    await session.commit()
    await callback.answer(f"🎭 Режим Incognito {'включен' if user.is_incognito else 'выключен'}")
    await show_settings(callback, session, ui)

@router.callback_query(SellerSettingsCD.filter(F.action == "notif"))
async def show_notif_settings(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Отображение настроек уведомлений."""
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        pref = user.notification_preference.value
        
        status_map = {
            "full": "🟢 ВКЛЮЧЕНЫ (Все)",
            "summary": "🟡 ИТОГ ЗА ДЕНЬ",
            "none": "🔴 ВЫКЛЮЧЕНЫ"
        }
        
        text = (
            "🔔 <b>ЦЕНТР УВЕДОМЛЕНИЙ</b>\n\n"
            "Настройте получение оперативных отчетов о проверке ваших eSIM.\n\n"
            f"📊 <b>ТЕКУЩИЙ СТАТУС:</b> {status_map.get(pref, 'Неизвестно')}\n"
            f"{DIVIDER_LIGHT}\n"
            "<i>Выберите желаемый режим:</i>"
        )
        kb = await get_notification_settings_kb(pref)
        await ui.display(event=callback, text=text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_notif_settings: {e}")
        await callback.answer("⚠️ Ошибка уведомлений", show_alert=True)

@router.callback_query(SellerNotifCD.filter())
async def set_notification_pref(callback: CallbackQuery, callback_data: SellerNotifCD, session: AsyncSession, ui: MessageManager) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    user.notification_preference = NotificationPreference(callback_data.preference)
    await session.commit()
    await callback.answer("✅ Настройки сохранены", show_alert=True)
    await show_notif_settings(callback, session, ui)

@router.callback_query(SellerSettingsCD.filter(F.action == "lang"))
async def show_language_settings(callback: CallbackQuery, ui: MessageManager) -> None:
    """Выбор языка интерфейса."""
    try:
        text = (
            "🌐 <b>ЯЗЫК / LANGUAGE</b>\n\n"
            "Выберите язык интерфейса платформы.\n"
            "<i>На данный момент доступен только русский язык.</i>"
        )
        await ui.display(event=callback, text=text, reply_markup=await get_language_settings_kb())
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_language_settings: {e}")
        await callback.answer("⚠️ Ошибка выбора языка", show_alert=True)

@router.callback_query(SellerSettingsCD.filter(F.action == "lang_set"))
async def set_language(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Установка языка."""
    await callback.answer("✅ Язык интерфейса: RU", show_alert=True)
    await show_settings(callback, session, ui)

# --- ПРОЧЕЕ ---

@router.callback_query(SellerMenuCD.filter(F.action == "stats"))
@router.callback_query(SellerStatsCD.filter())
async def show_stats(callback: CallbackQuery, callback_data: SellerMenuCD | SellerStatsCD, session: AsyncSession, ui: MessageManager) -> None:
    try:
        period = callback_data.period if isinstance(callback_data, SellerStatsCD) else "all"
        
        # Если мы в режиме выплат, редиректим
        msg_text = (callback.message.text or callback.message.caption or "").upper()
        if "PAYOUT" in msg_text or "ВЫПЛАТ" in msg_text:
            return await _render_payout_history(callback, session, ui, period=period)

        days_map = {"day": 1, "week": 7, "month": 30, "all": None}
        label_map = {"day": "Сутки", "week": "Неделя", "month": "Месяц", "all": "Все время"}
        
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        sub_svc = SubmissionService(session=session)
        stats = await sub_svc.get_detailed_stats_for_period(user.id, days_map.get(period))
        rank_pos = await sub_svc.get_user_rank_position(user.id)
        
        text = _renderer.render_seller_stats(label_map.get(period, "Все время"), stats, rank_pos)
        kb = await get_seller_stats_kb(period)
        
        # Добавляем баннер статистики
        banner = media.get("state.jpg")
        await ui.display(event=callback, text=text, reply_markup=kb, photo=banner)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_stats: {e}")
        await callback.answer("⚠️ Ошибка статистики", show_alert=True)

@router.callback_query(SellerSettingsCD.filter(F.action == "prefs"))
async def show_prefs_favorites(callback: CallbackQuery, callback_data: SellerSettingsCD, session: AsyncSession, ui: MessageManager) -> None:
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        cat_svc = CategoryService(session=session)
        
        if callback_data.value:
            cat_id = int(callback_data.value)
            favs = list(user.favorite_categories or [])
            if cat_id in favs:
                favs.remove(cat_id)
                await callback.answer("❌ Удалено из избранного")
            else:
                favs.append(cat_id)
                await callback.answer("⭐ Добавлено в избранное")
            user.favorite_categories = favs
            flag_modified(user, "favorite_categories")
            await session.commit()

        categories = await cat_svc.get_active_categories()
        text = (
            "⭐ <b>GDPX // ИЗБРАННЫЕ ОПЕРАТОРЫ</b>\n"
            f"{DIVIDER}\n"
            "Отметьте категории, которыми вы пользуетесь чаще всего.\n"
            "Они будут отображаться в самом верху списка при загрузке eSIM."
        )
        kb = await get_favorite_categories_kb(categories, user.favorite_categories or [])
        await ui.display(event=callback, text=text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in show_prefs_favorites: {e}")
        await callback.answer("⚠️ Ошибка настроек", show_alert=True)

@router.callback_query(SellerSettingsCD.filter(F.action == "export"))
async def export_data_request(callback: CallbackQuery, callback_data: SellerSettingsCD, session: AsyncSession) -> None:
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        sub_svc = SubmissionService(session=session)
        await callback.answer("📊 Формируем отчет... Это может занять несколько секунд.")
        
        # Определяем период для экспорта
        period = "all"
        caption = f"📋 <b>Ваш экспорт данных готов</b>\n{DIVIDER}\nВсе загруженные активы за всё время работы в системе."
        
        if callback_data.value.startswith("arch_"):
            period = callback_data.value.replace("arch_", "")
            labels = {"yesterday": "вчера", "7d": "7 дней", "30d": "30 дней", "all": "всё время"}
            caption = f"📋 <b>Ваш архивный экспорт готов</b>\n{DIVIDER}\nПериод: <code>{labels.get(period, period)}</code>"

        excel_data = await sub_svc.export_user_submissions_excel(user.id) # Пока без фильтра периода в сервисе
        filename = f"GDPX_Report_{user.telegram_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        await callback.message.answer_document(
            document=BufferedInputFile(excel_data, filename=filename),
            caption=caption,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"Error in export_data_request: {e}")
        await callback.answer("⚠️ Ошибка экспорта", show_alert=True)
