"""Knowledge Base, FAQ, manuals, and support handlers for the seller module."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InputMediaPhoto,
)

from src.core.config import get_settings
from src.faq import FAQ_CARDS, get_faq_by_id
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import SellerInfoCD, SellerMenuCD
from src.keyboards.info import (
    get_back_to_info_kb,
    get_back_to_manual_level_kb,
    get_faq_list_kb,
    get_info_root_kb,
    get_manual_levels_kb,
    get_manuals_in_level_kb,
)
from src.manuals import MANUAL_LEVELS, get_manual_by_id, get_manuals_by_level
from src.utils.media import media
from src.utils.text_format import edit_message_text_or_caption_safe
from src.utils.ui_builder import DIVIDER

router = Router(name="seller-info-router")


def _info_root_text() -> str:
    return (
        "<b>❖ GDPX // БАЗА ЗНАНИЙ</b>\n\n"
        "Добро пожаловать в закрытую Академию GDPX. Здесь собраны все необходимые "
        "протоколы и регламенты для эффективной работы с eSIM.\n\n"
        "<b>СТРУКТУРА БАЗЫ:</b>\n"
        "❂ <b>GDPX // ACADEMY //</b>\n"
        "└ Прямой чат сообщества и оперативная поддержка.\n\n"
        "❂ <b>F.A.Q. //</b>\n"
        "└ Ответы на финансовые и технические вопросы.\n\n"
        "❂ <b>МАНУАЛЫ //</b>\n"
        "└ Пошаговые алгоритмы действий для селлеров.\n\n"
        f"{DIVIDER}\n"
        "<i>Изучите материалы перед началом работы. Знания — это ваш капитал.</i>"
    )


from src.core.logger import logger

# --- БАЗА ЗНАНИЙ (ГЛАВНАЯ) ---


@router.callback_query(F.data == "mod_exit")  # Возврат из подразделов (обработка селлерского меню)
@router.callback_query(SellerMenuCD.filter(F.action == "info"))
async def on_info_root(callback: CallbackQuery):
    """Главный экран Базы Знаний."""
    try:
        settings = get_settings()
        filename = "baza.jpg"
        banner = media.get(filename)

        await callback.answer()
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=_info_root_text(), parse_mode="HTML"),
                reply_markup=get_info_root_kb(settings.brand_chat_url, settings.brand_channel_url),
            )
        except Exception:
            await edit_message_text_or_caption_safe(
                callback.message,
                _info_root_text(),
                reply_markup=get_info_root_kb(settings.brand_chat_url, settings.brand_channel_url),
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception(f"Error in on_info_root: {e}")
        await callback.answer("⚠️ Ошибка при открытии Базы Знаний", show_alert=True)


# --- F.A.Q. ---


@router.callback_query(SellerMenuCD.filter(F.action == "faq"))
async def on_info_faq(callback: CallbackQuery):
    """Список вопросов FAQ."""
    try:
        filename = "faq.jpg"
        banner = media.get(filename)

        text = (
            f"❖ <b>GDPX // F.A.Q.</b>\n"
            f"{DIVIDER}\n"
            f"База ответов на часто задаваемые вопросы.\n"
            f"Выберите интересующую категорию:\n\n"
            f"📡 <b>STATUS:</b> <code>STABLE</code>"
        )

        await callback.answer()
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=get_faq_list_kb(FAQ_CARDS),
        )
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
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
            reply_markup=get_back_to_info_kb("faq"),
        )
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
            f"❖ <b>GDPX // МАНУАЛЫ</b>\n"
            f"{DIVIDER}\n"
            f"Выберите уровень подготовки для изучения методологии:\n\n"
            f"📡 <b>STATUS:</b> <code>READY</code>"
        )

        await callback.answer()
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=get_manual_levels_kb(MANUAL_LEVELS),
        )
    except Exception as e:
        logger.exception(f"Error in on_info_manuals: {e}")
        await callback.answer("⚠️ Ошибка при открытии Мануалов", show_alert=True)


@router.callback_query(SellerInfoCD.filter(F.type == "manual_lvl"))
async def on_manual_level(callback: CallbackQuery, callback_data: SellerInfoCD):
    """Список мануалов внутри уровня."""
    try:
        level = next((lvl for lvl in MANUAL_LEVELS if lvl.id == callback_data.id), None)
        if not level:
            return await callback.answer("❌ Уровень не найден", show_alert=True)

        filename = "baza.jpg"
        banner = media.get(filename)

        manuals = get_manuals_by_level(level.id)
        text = (
            f"❖ <b>{level.emoji} {level.title}</b>\n{DIVIDER}\n<i>Выберите интересующий протокол для ознакомления:</i>"
        )

        await callback.answer()
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=get_manuals_in_level_kb(manuals),
        )
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
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
            reply_markup=get_back_to_manual_level_kb(card.level),
        )
    except Exception as e:
        logger.exception(f"Error in on_manual_item: {e}")
        await callback.answer("⚠️ Ошибка при чтении мануала", show_alert=True)


# --- SUPPORT CENTER ---
@router.callback_query(SellerMenuCD.filter(F.action == "support"))
async def on_support_center(callback: CallbackQuery):
    """Новый раздел SUPPORT CENTER."""
    try:
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
            f"[🟢 <b>ONLINE</b>] — <i>Пишите сразу по существу вопроса.</i>"
        )

        kb = PremiumBuilder().back("mod_exit", "❮ НАЗАД").as_markup()

        await callback.answer()
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=kb
        )
    except Exception as e:
        logger.exception(f"Error in on_support_center: {e}")
        await callback.answer("⚠️ Ошибка при открытии Поддержки", show_alert=True)
