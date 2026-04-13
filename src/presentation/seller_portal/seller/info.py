"""Knowledge Base, FAQ, manuals, and support handlers for the seller module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InputMediaPhoto,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.content_loader import (
    get_faq_by_id,
    get_faq_cards,
    get_manual_by_id,
    get_manual_levels,
    get_manuals_by_level,
)
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import NavCD, SellerArchiveCD, SellerInfoCD, SellerMenuCD
from src.presentation.seller_portal.info import (
    get_back_to_info_kb,
    get_back_to_manual_level_kb,
    get_faq_list_kb,
    get_info_root_kb,
    get_manual_levels_kb,
    get_manuals_in_level_kb,
)
from .keyboards import get_seller_archive_kb
from src.domain.moderation.admin_stats_service import AdminStatsService
from src.domain.users.user_service import UserService
from src.core.utils.media import media
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT

router = Router(name="seller-info-router")


@router.callback_query(SellerMenuCD.filter(F.action == "archive"))
@router.callback_query(SellerArchiveCD.filter())
async def on_archive_open(
    callback: CallbackQuery, 
    callback_data: SellerMenuCD | SellerArchiveCD, 
    session: AsyncSession,
    ui: MessageManager
) -> None:
    """Отрисовка раздела Архив с детальной статистикой."""
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        
        # 1. Определение периода
        period = "all"
        if isinstance(callback_data, SellerArchiveCD):
            period = callback_data.period
            
        # 2. Вычисление start_date для статистики (по МСК)
        now_utc = datetime.now(timezone.utc)
        start_date = None
        
        if period == "yesterday":
            msk_tz = timezone(timedelta(hours=3))
            today_msk = datetime.now(msk_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_msk = today_msk - timedelta(days=1)
            start_date = yesterday_msk.astimezone(timezone.utc)
        elif period == "7d":
            start_date = now_utc - timedelta(days=7)
        elif period == "30d":
            start_date = now_utc - timedelta(days=30)
            
        # 3. Сбор данных
        stats_svc = AdminStatsService(session)
        stats = await stats_svc.get_user_archive_stats(user.id, start_date)
        
        period_labels = {
            "yesterday": "ВЧЕРА",
            "7d": "ПОСЛЕДНИЕ 7 ДНЕЙ",
            "30d": "ПОСЛЕДНИЕ 30 ДНЕЙ",
            "all": "ЗА ВСЁ ВРЕМЯ"
        }
        
        label = period_labels.get(period, "АРХИВ")
        
        # 4. Формирование текста кластеров
        clusters_text = ""
        if stats["clusters"]:
            clusters_text = "\n📦 <b>КЛАСТЕРЫ В АРХИВЕ:</b>\n"
            for c in stats["clusters"]:
                clusters_text += f" ├ {c['title']}: <code>{c['count']}</code> шт.\n"
        
        text = (
            f"📦 <b>АРХИВ // STORAGE</b>\n"
            f"📅 <b>Период:</b> <code>{label}</code>\n"
            f"{DIVIDER}\n"
            f"🟢 <b>Принято:</b> <code>{stats['accepted']}</code> шт.\n"
            f"🔴 <b>Брак:</b> <code>{stats['rejected']}</code> шт.\n"
            f"🚫 <b>Блок:</b> <code>{stats['blocked']}</code> шт.\n"
            f"📵 <b>Не скан:</b> <code>{stats['not_a_scan']}</code> шт.\n\n"
            f"💰 <b>Ценность:</b> <code>{stats['total_value']:.2f}</code> USDT\n"
            f"⭐ <b>Сред. ставка:</b> <code>{stats['avg_rate']:.2f}</code> USDT\n"
            f"{clusters_text}"
            f"{DIVIDER_LIGHT}\n"
            f"<i>В архиве хранятся активы, загруженные до 00:00 МСК текущего дня.</i>"
        )
        
        banner = media.get("archive.jpg")
        kb = await get_seller_archive_kb(period)
        
        await ui.display(event=callback, text=text, reply_markup=kb, photo=banner)
        await callback.answer()
        
    except Exception as e:
        logger.exception(f"Archive error: {e}")
        await callback.answer("⚠️ Ошибка открытия архива", show_alert=True)


def _info_root_text() -> str:
    return (
        "<b>❖ GDPX // СТРУКТУРА БАЗЫ:</b>\n"
        f"{DIVIDER}\n\n"
        "Добро пожаловать в закрытую <b>Академию GDPX</b>.\n\n"
        "- <i>Здесь собраны все необходимые протоколы\n"
        "и регламенты для эффективной работы с eSIM.</i>\n\n"
        "❂ <b>GDPX // ACADEMIC CHAT</b>\n"
        "└ <i>Прямой чат сообщества и оперативная поддержка.</i>\n\n"
        "❂ <b>F.A.Q.</b>\n"
        "└ <i>Ответы на финансовые и технические вопросы.</i>\n\n"
        "❂ <b>Мануалы.</b>\n"
        "└ <i>Пошаговые алгоритмы действий для селлеров.</i>\n\n"
        f"{DIVIDER}\n"
        "Изучите материалы перед началом работы.\n" 
        "Знания - ваш капитал."
    )


from aiogram.filters import Command

from src.core.logger import logger

# --- БАЗА ЗНАНИЙ (ГЛАВНАЯ) ---


@router.callback_query(SellerMenuCD.filter(F.action == "info"))
async def on_info_root(event: Message | CallbackQuery, state: FSMContext):
    """Главный экран Базы Знаний."""
    try:
        await state.clear()
        settings = get_settings()
        filename = "baza.jpg"
        banner = media.get(filename)

        kb = get_info_root_kb(settings.brand_chat_url, settings.brand_channel_url)
        text = _info_root_text()

        if isinstance(event, Message):
            await event.answer_photo(photo=banner, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer()
            try:
                await event.message.edit_media(
                    media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                    reply_markup=kb,
                )
            except Exception:
                await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb)
    except Exception as e:
        logger.exception(f"Error in on_info_root: {e}")
        if isinstance(event, CallbackQuery):
            await event.answer("⚠️ Ошибка открытия базы", show_alert=True)


# --- F.A.Q. ---


@router.callback_query(SellerMenuCD.filter(F.action == "faq"))
async def on_info_faq(callback: CallbackQuery):
    """Список вопросов FAQ."""
    try:
        filename = "faq.jpg"
        banner = media.get(filename)

        text = (
            f"❖ <b>GDPX // F.A.Q. - ВОПРОСЫ</b>\n"
            f"{DIVIDER}\n"
            f"База ответов на часто задаваемые вопросы.\n"
            f"Выберите интересующую категорию:\n\n"
        )

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=get_faq_list_kb(get_faq_cards()),
            )
        except Exception:
            await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_faq_list_kb(get_faq_cards()))
    except Exception as e:
        logger.exception(f"Error in on_info_faq: {e}")
        await callback.answer("⚠️ Ошибка при открытии FAQ", show_alert=True)


@router.callback_query(SellerInfoCD.filter(F.type == "faq"))
async def on_faq_item(callback: CallbackQuery, callback_data: SellerInfoCD):
    """Просмотр конкретного вопроса FAQ."""
    try:
        card = get_faq_by_id(callback_data.id)
        if not card:
            return await callback.answer("❌ FAQ не найден", show_alert=True)

        filename = "faq.jpg"
        banner = media.get(filename)

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
                reply_markup=get_back_to_info_kb("faq"),
            )
        except Exception:
            await edit_message_text_or_caption_safe(callback.message, card.text, reply_markup=get_back_to_info_kb("faq"))
    except Exception as e:
        logger.exception(f"Error in on_faq_item: {e}")
        await callback.answer("⚠️ Ошибка при чтении статьи", show_alert=True)


# --- МАНУАЛЫ ---


@router.callback_query(SellerMenuCD.filter(F.action == "manuals"))
async def on_info_manuals(callback: CallbackQuery):
    """Главный экран мануалов (выбор уровней)."""
    try:
        filename = "info.jpg"
        banner = media.get(filename)

        text = (
            f"❖ <b>GDPX // МАНУАЛЫ [3 УРОВНЯ]</b>\n"
            f"{DIVIDER}\n"
            f"Выберите уровень подготовки для изучения методологии:\n\n"
        )

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=get_manual_levels_kb(get_manual_levels()),
            )
        except Exception:
            await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_manual_levels_kb(get_manual_levels()))
    except Exception as e:
        logger.exception(f"Error in on_info_manuals: {e}")
        await callback.answer("⚠️ Ошибка при открытии Мануалов", show_alert=True)


@router.callback_query(SellerInfoCD.filter(F.type == "manual_lvl"))
async def on_manual_level(callback: CallbackQuery, callback_data: SellerInfoCD):
    """Список мануалов внутри уровня."""
    try:
        manual_levels = get_manual_levels()
        level = next((lvl for lvl in manual_levels if lvl.id == callback_data.id), None)
        if not level:
            return await callback.answer("❌ Уровень не найден", show_alert=True)

        filename = "baza.jpg"
        banner = media.get(filename)

        manuals = get_manuals_by_level(level.id)
        text = (
            f"❖ <b>{level.emoji} {level.title}</b>\n{DIVIDER}\n<i>Выберите интересующий протокол для ознакомления:</i>"
        )

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=get_manuals_in_level_kb(manuals),
            )
        except Exception:
            await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_manuals_in_level_kb(manuals))
    except Exception as e:
        logger.exception(f"Error in on_manual_level: {e}")
        await callback.answer("⚠️ Ошибка при открытии уровня", show_alert=True)


@router.callback_query(SellerInfoCD.filter(F.type == "manual_item"))
async def on_manual_item(callback: CallbackQuery, callback_data: SellerInfoCD):
    """Просмотр текста мануала."""
    try:
        card = get_manual_by_id(callback_data.id)
        if not card:
            return await callback.answer("❌ Мануал не найден", show_alert=True)

        filename = "info.jpg"
        banner = media.get(filename)

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
                reply_markup=get_back_to_manual_level_kb(card.level),
            )
        except Exception:
            await edit_message_text_or_caption_safe(callback.message, card.text, reply_markup=get_back_to_manual_level_kb(card.level))
    except Exception as e:
        logger.exception(f"Error in on_manual_item: {e}")
        await callback.answer("⚠️ Ошибка при чтении мануала", show_alert=True)


# --- SUPPORT CENTER ---

@router.message(Command("help"))
@router.callback_query(SellerMenuCD.filter(F.action == "support"))
async def on_support_center(event: Message | CallbackQuery, state: FSMContext):
    """Штаб оперативной связи (Поддержка)."""
    try:
        await state.clear()
        filename = "support.jpg"
        banner = media.get(filename)

        text = (
            f"❖ <b>GDPX // SUPPORT CENTER</b>\n"
            f"{DIVIDER}\n"
            f"Штаб оперативной связи с командой проекта.\n\n"
            f"🌑 <b>ОСНОВАТЕЛЬ</b> — @GDPX1\n"
            f" └ <i>Ресурсная база / Глобальный выкуп</i>\n\n"
            f"🛡 <b>САППОРТЫ</b> — @oduvan_kenoby | @hdksiwns\n"
            f" └ <i>Наставление / Прием материала.</i>\n\n"
            f"⚙️ <b>АРХИТЕКТОР</b> — @brug0S\n"
            f" └ <i>Бот / Технические вопросы.</i>\n"
            f"{DIVIDER}\n"
            f"[<b>ONLINE</b>] — <i>Пишите сразу по существу вопроса.</i>"
        )

        kb = PremiumBuilder().back(NavCD(to="menu"), "❮ В ГЛАВНОЕ МЕНЮ").as_markup()

        if isinstance(event, Message):
            await event.answer_photo(photo=banner, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await event.answer()
            try:
                await event.message.edit_media(
                    media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=kb
                )
            except Exception:
                await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb)
    except Exception as e:
        logger.exception(f"Error in on_support_center: {e}")
        if isinstance(event, CallbackQuery):
            await event.answer("⚠️ Ошибка при открытии Поддержки", show_alert=True)
