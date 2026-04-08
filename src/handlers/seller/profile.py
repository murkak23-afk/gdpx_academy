from __future__ import annotations

import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InputMediaPhoto, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.services.badge_service import BadgeService
from src.services.category_service import CategoryService
from src.database.models.enums import NotificationPreference
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer, DIVIDER
from src.keyboards.factory import SellerMenuCD, NavCD, SellerStatsCD, SellerSettingsCD, PinPadCD, SellerNotifCD
from src.keyboards import (
    get_seller_main_kb as get_premium_seller_kb, 
    get_back_to_main_kb, 
    get_seller_profile_kb,
    get_seller_stats_kb,
    get_seller_settings_kb,
    get_pin_pad_kb,
    get_notification_settings_kb,
    get_favorite_categories_kb
)
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="seller-profile-premium-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

@router.callback_query(SellerMenuCD.filter(F.action == "profile"))
@router.callback_query(NavCD.filter(F.to == "menu"))
async def show_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    """Обновление экрана профиля или главного меню."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_svc = SubmissionService(session=session)
    dashboard = await sub_svc.get_user_dashboard_stats(user.id)
    
    # Определяем, что именно отрисовывать
    is_main_menu = "nav:menu" in (callback.data if isinstance(callback.data, str) else callback.data.pack())
    
    if is_main_menu:
        stats = {
            "username": user.nickname or user.pseudonym or user.username or str(user.telegram_id),
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "total_payout_amount": float(user.total_paid or 0)
        }
        text = _renderer.render_dashboard(stats)
        has_accepted = getattr(user, "has_accepted_codex", False)
        kb = get_premium_seller_kb(has_accepted_codex=has_accepted)
        banner = media.get("main.jpg")
    else:
        # Рассчитываем динамические значки
        user.badges = BadgeService.calculate_badges(user, dashboard)
        
        recent = await sub_svc.list_user_material_by_category_paginated(
            user_id=user.id,
            category_id=0,
            page=0,
            page_size=5,
            statuses=None
        )
        items = recent[0] if isinstance(recent, tuple) else recent
        
        text = _renderer.render_seller_profile_premium(
            user=user,
            stats=dashboard,
            recent_submissions=items
        )
        kb = get_seller_profile_kb()
        banner = media.get("profile.jpg")
    
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=kb
        )
    except Exception:
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "stats"))
@router.callback_query(SellerStatsCD.filter())
async def show_stats(callback: CallbackQuery, callback_data: SellerMenuCD | SellerStatsCD, session: AsyncSession) -> None:
    period = callback_data.period if isinstance(callback_data, SellerStatsCD) else "all"
    days_map = {"day": 1, "week": 7, "month": 30, "all": None}
    label_map = {"day": "Сутки", "week": "Неделя", "month": "Месяц", "all": "Все время"}
    
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_svc = SubmissionService(session=session)
    stats = await sub_svc.get_detailed_stats_for_period(user.id, days_map.get(period))
    rank_pos = await sub_svc.get_user_rank_position(user.id)
    
    text = _renderer.render_seller_stats(label_map.get(period, "Все время"), stats, rank_pos)
    kb = get_seller_stats_kb(period)
    await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "settings"))
@router.callback_query(SellerSettingsCD.filter(F.action == "main"))
async def show_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    text = _renderer.render_seller_settings(user)
    kb = get_seller_settings_kb()
    await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(SellerSettingsCD.filter(F.action == "incognito"))
async def toggle_incognito(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    user.is_incognito = not user.is_incognito
    await session.commit()
    await callback.answer(f"🎭 Режим Incognito {'включен' if user.is_incognito else 'выключен'}")
    await show_settings(callback, session)

@router.callback_query(SellerSettingsCD.filter(F.action == "notif"))
async def show_notif_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    text = _renderer.render_notification_settings(user.notification_preference.value)
    kb = get_notification_settings_kb()
    await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(SellerNotifCD.filter())
async def set_notification_pref(callback: CallbackQuery, callback_data: SellerNotifCD, session: AsyncSession) -> None:
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    user.notification_preference = NotificationPreference(callback_data.preference)
    await session.commit()
    await callback.answer("✅ Настройки уведомлений сохранены")
    await show_notif_settings(callback, session)

@router.callback_query(SellerSettingsCD.filter(F.action == "prefs"))
async def show_prefs_favorites(callback: CallbackQuery, callback_data: SellerSettingsCD, session: AsyncSession) -> None:
    """Управление избранными операторами."""
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
    kb = get_favorite_categories_kb(categories, user.favorite_categories or [])
    await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(SellerSettingsCD.filter(F.action == "export"))
async def export_data_request(callback: CallbackQuery, session: AsyncSession) -> None:
    """Генерация и отправка Excel-отчета."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_svc = SubmissionService(session=session)
    await callback.answer("📊 Формируем отчет... Это может занять несколько секунд.")
    excel_data = await sub_svc.export_user_submissions_excel(user.id)
    filename = f"GDPX_Report_{user.telegram_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    await callback.message.answer_document(
        document=BufferedInputFile(excel_data, filename=filename),
        caption=f"📋 <b>Ваш экспорт данных готов</b>\n{DIVIDER}\nВсе загруженные активы за всё время работы в системе.",
        parse_mode="HTML"
    )

@router.callback_query(SellerSettingsCD.filter(F.action == "pin"))
async def start_pin_setup(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(pin_input="", pin_context="setup")
    text = _renderer.render_pin_pad("", "УСТАНОВКА PIN-КОДА")
    kb = get_pin_pad_kb("", "setup")
    await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(PinPadCD.filter(F.action == "digit"))
async def pin_digit(callback: CallbackQuery, callback_data: PinPadCD, state: FSMContext) -> None:
    data = await state.get_data()
    current = data.get("pin_input", "")
    if len(current) < 6:
        current += callback_data.value
        await state.update_data(pin_input=current)
        text = _renderer.render_pin_pad(current, "ВВОД PIN-КОДА")
        kb = get_pin_pad_kb(current, callback_data.context)
        await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(PinPadCD.filter(F.action == "backspace"))
async def pin_backspace(callback: CallbackQuery, callback_data: PinPadCD, state: FSMContext) -> None:
    data = await state.get_data()
    current = data.get("pin_input", "")
    if current:
        current = current[:-1]
        await state.update_data(pin_input=current)
        text = _renderer.render_pin_pad(current, "ВВОД PIN-КОДА")
        kb = get_pin_pad_kb(current, callback_data.context)
        await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(PinPadCD.filter(F.action == "confirm"))
async def pin_confirm(callback: CallbackQuery, callback_data: PinPadCD, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    pin = data.get("pin_input", "")
    if callback_data.context == "setup":
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        user.pin_code = pin
        user.is_pin_enabled = True
        await session.commit()
        await callback.answer("✅ PIN-код успешно установлен!", show_alert=True)
        await show_settings(callback, session)
    await state.update_data(pin_input="")
    await callback.answer()

@router.callback_query(PinPadCD.filter(F.action == "cancel"))
async def pin_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.update_data(pin_input="")
    await show_settings(callback, session)
    await callback.answer()
