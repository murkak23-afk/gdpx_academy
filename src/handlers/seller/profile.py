from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.database.models.publication import Payout
from src.database.models.enums import PayoutStatus
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer, DIVIDER
from src.keyboards.factory import SellerMenuCD, NavCD, SellerInfoCD
from src.keyboards.builders import (
    get_seller_main_kb, get_info_root_kb, get_faq_list_kb, 
    get_manual_levels_kb, get_manuals_in_level_kb, get_back_to_manual_level_kb, get_back_to_info_kb
)
from src.utils.text_format import edit_message_text_or_caption_safe

# Подключаем данные FAQ и Мануалов
from src.faq import FAQ_CARDS, get_faq_by_id
from src.manuals import MANUAL_LEVELS, get_manual_by_id, get_manuals_by_level

router = Router(name="seller-profile-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

@router.callback_query(SellerMenuCD.filter(F.action == "profile"))
async def show_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    """Обновление экрана профиля (баннер profile.jpg)."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user.id)
    
    text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        },
        user.telegram_id,
    )
    
    banner = media.get("profile.jpg")
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=get_seller_main_kb()
        )
    except Exception:
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_seller_main_kb())
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "payouts"))
async def show_payouts(callback: CallbackQuery, session: AsyncSession) -> None:
    """Экран выплат (баннер payouts.jpg)."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    stmt_paid = select(func.sum(Payout.amount)).where(Payout.user_id == user.id, Payout.status == PayoutStatus.PAID)
    total_paid = (await session.execute(stmt_paid)).scalar() or 0
    
    text = (
        f"<b>❖ GDPX // FINANCE</b>\n"
        f"{DIVIDER}\n"
        f"💸 <b>К ВЫПЛАТЕ (СЕГОДНЯ):</b> <code>{user.pending_balance}</code> USDT\n"
        f"💎 <b>ВСЕГО ВЫПЛАЧЕНО:</b> <code>{total_paid}</code> USDT\n\n"
        f"<i>Инфо: выплаты производятся ежедневно в вечернее время.</i>\n"
        f"{DIVIDER}"
    )
    
    banner = media.get("payouts.jpg")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ Назад", callback_data=NavCD(to="menu").pack())]])
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), 
            reply_markup=kb
        )
    except Exception:
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "info"))
async def show_info(callback: CallbackQuery) -> None:
    """Экран Кодекса (баннер info.jpg)."""
    text = (
        "<b>❖ GDPX // INFO CENTER</b>\n\n"
        "Доступ к методологии GDPX ACADEMY открыт. Вы вошли в закрытый лекторий.\n"
        "Здесь знания конвертируются в капитал по высшим стандартам качества.\n\n"
        "<b>АРХИТЕКТУРА РАЗДЕЛА:</b>\n"
        "❂ <b>F.A.Q. //</b>\n"
        "└ Свод протоколов по финансовым и техническим вопросам.\n\n"
        "❂ <b>МАНУАЛЫ //</b>\n"
        "└ Пошаговые алгоритмы действий для полевых агентов.\n\n"
        f"{DIVIDER}\n"
        "<i>Выберите целевой сектор управления кнопками ниже.</i>"
    )
    
    banner = media.get("info.jpg")
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=get_info_root_kb()
        )
    except Exception:
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_info_root_kb())
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "support"))
async def show_support(callback: CallbackQuery) -> None:
    """Экран техподдержки (баннер support.jpg)."""
    text = (
        f"❖ <b>GDPX // SUPPORT CENTER</b>\n"
        f"{DIVIDER}\n"
        f"🌑 <b>ОСНОВАТЕЛЬ</b> - @GDPX1\n"
        f"  └ <i>Ресурсная база / Глобальный выкуп</i>\n\n"
        f"🛡 <b>САППОРТЫ</b> - @oduvan_kenoby | @hdksiwns\n"
        f"  └ <i>Наставление / Прием материала</i>\n\n"
        f"⚙️ <b>АРХИТЕКТОР</b> - @brug0S\n"
        f"  └ <i>Технические вопросы / Бот</i>\n"
        f"{DIVIDER}\n"
        f"✦ <b>ONLINE</b> // <i>Отклик: 15 MIN.</i>"
    )
    banner = media.get("support.jpg")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ Назад", callback_data=NavCD(to="menu").pack())]])
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), 
            reply_markup=kb
        )
    except Exception:
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb)
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "faq"))
async def list_faq(callback: CallbackQuery) -> None:
    """Список вопросов FAQ (баннер faq.jpg)."""
    text = "<b>❖ GDPX ACADEMY // FAQ</b>\n\nВыберите интересующий вопрос:"
    banner = media.get("faq.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
        reply_markup=get_faq_list_kb(FAQ_CARDS)
    )
    await callback.answer()

@router.callback_query(SellerMenuCD.filter(F.action == "manuals"))
async def list_manual_levels(callback: CallbackQuery) -> None:
    """Список уровней мануалов (баннер baza.jpg)."""
    text = "<b>❖ GDPX ACADEMY // МАНУАЛЫ</b>\n\nДоступные уровни подготовки:"
    banner = media.get("baza.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
        reply_markup=get_manual_levels_kb(MANUAL_LEVELS)
    )
    await callback.answer()

@router.callback_query(SellerInfoCD.filter(F.type == "manual_lvl"))
async def list_manuals_in_level(callback: CallbackQuery, callback_data: SellerInfoCD) -> None:
    """Список мануалов в уровне."""
    level = next((lvl for lvl in MANUAL_LEVELS if lvl.id == callback_data.id), None)
    if not level:
        await callback.answer("Уровень не найден", show_alert=True)
        return
    manuals = get_manuals_by_level(level.id)
    text = f"<b>❖ {level.emoji} {level.title}</b>\n{DIVIDER}\nВыберите мануал:"
    banner = media.get("baza.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
        reply_markup=get_manuals_in_level_kb(manuals)
    )
    await callback.answer()

@router.callback_query(SellerInfoCD.filter(F.type == "manual_item"))
async def show_manual_detail(callback: CallbackQuery, callback_data: SellerInfoCD) -> None:
    """Отображение мануала."""
    card = get_manual_by_id(callback_data.id)
    if not card:
        await callback.answer("Мануал не найден", show_alert=True)
        return
    banner = media.get("baza.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
        reply_markup=get_back_to_manual_level_kb(card.level)
    )
    await callback.answer()

@router.callback_query(SellerInfoCD.filter(F.type == "faq"))
async def show_faq_detail(callback: CallbackQuery, callback_data: SellerInfoCD) -> None:
    """Отображение статьи FAQ."""
    card = get_faq_by_id(callback_data.id)
    if not card:
        await callback.answer("FAQ не найден", show_alert=True)
        return
    banner = media.get("faq.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
        reply_markup=get_back_to_info_kb("faq")
    )
    await callback.answer()
