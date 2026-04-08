"""Info center, FAQ, manuals, and support handlers for the seller module."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    FSInputFile,
    InputMediaPhoto,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.faq import FAQ_CARDS, get_faq_by_id
from src.keyboards import get_seller_main_kb
from src.keyboards.callbacks import (
    CB_SELLER_FAQ_OPEN,
    CB_SELLER_INFO_FAQ,
    CB_SELLER_INFO_MANUALS,
    CB_SELLER_INFO_ROOT,
    CB_SELLER_MANUAL_LEVEL,
    CB_SELLER_MANUAL_OPEN,
    CB_SELLER_MENU_INFO,
    CB_SELLER_MENU_PROFILE,
    CB_SELLER_MENU_SUPPORT,
)

from src.manuals import MANUAL_LEVELS, get_manual_by_id, get_manuals_by_level
from src.services import UserService
from src.utils.clean_screen import send_clean_text_screen
from src.utils.text_format import edit_message_text_safe
from src.utils.media import media

from ._shared import DIVIDER

router = Router(name="seller-info-router")


# ── Keyboard builders ─────────────────────────────────────────────────────


def _manuals_levels_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for lvl in MANUAL_LEVELS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{lvl.emoji} {lvl.title}",
                    callback_data=f"{CB_SELLER_MANUAL_LEVEL}:{lvl.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ В INFO", callback_data=CB_SELLER_INFO_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manuals_level_keyboard(level_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for m in get_manuals_by_level(level_id):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{m.emoji} {m.title}",
                    callback_data=f"{CB_SELLER_MANUAL_OPEN}:{m.id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ К уровням", callback_data=CB_SELLER_INFO_MANUALS)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manual_detail_keyboard(level_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"{CB_SELLER_MANUAL_LEVEL}:{level_id}",
                )
            ],
        ]
    )


def _faq_list_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for f in FAQ_CARDS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{f.emoji} {f.title}",
                    callback_data=f"{CB_SELLER_FAQ_OPEN}:{f.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ В INFO", callback_data=CB_SELLER_INFO_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _faq_detail_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К FAQ", callback_data=CB_SELLER_INFO_FAQ)],
        ]
    )


def _info_root_keyboard(
    channel_url: str | None, chat_url: str | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    links_row: list[InlineKeyboardButton] = []
    if channel_url:
        links_row.append(InlineKeyboardButton(text="GDPX // ACADEMY", url=channel_url))
    if chat_url:
        links_row.append(
            InlineKeyboardButton(text="GDPX Academy | Чат", url=chat_url)
        )
    if links_row:
        rows.append(links_row)
    rows.append(
        [
            InlineKeyboardButton(text="📘 FAQ", callback_data=CB_SELLER_INFO_FAQ),
            InlineKeyboardButton(text="🧭 Мануалы", callback_data=CB_SELLER_INFO_MANUALS),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_SELLER_MENU_PROFILE)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _info_root_text() -> str:
    return (
        "<b>❖ GDPX // INFO CENTER</b>\n\n"
        "Доступ к методологии GDPX ACADEMY открыт. Вы вошли в закрытый лекторий.\n"
        "Здесь знания конвертируются в капитал по высшим стандартам качества.»\n\n"
        "<b>АРХИТЕКТУРА РАЗДЕЛА:</b>\n"
        "❂ <b>КОМЬЮИНИТИ //</b>\n"
        "└ Прямой доступ к штабу сообщества.\n\n"
        "❂ <b>F.A.Q. //</b>\n"
        "└ Свод протоколов по финансовым и техническим вопросам.\n\n"
        "❂ <b>МАНУАЛЫ //</b>\n"
        "└ Пошаговые алгоритмы действий для полевых агентов (селлеров).\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Выберите целевой сектор управления кнопками ниже.</i>"
    )


# ── Handlers ──────────────────────────────────────────────────────────────


@router.callback_query(F.data == CB_SELLER_MENU_SUPPORT)
async def on_seller_menu_support(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
        
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return

    # Подготовка визуала
    filename = "support.jpg"
    banner = media.get(filename)

    support_link = "@GDPX1"
    support_link2 = "@brug0S"
    helper_1 = "@oduvan_kenoby"
    helper_2 = "@hdksiwns"
    
    text = (
        f"❖ <b>GDPX // SUPPORT CENTER</b>\n"
        f"{DIVIDER}\n"
        f"🌑 <b>ОСНОВАТЕЛЬ</b> ── {support_link}\n"
        f"  └─<i>Ресурсная база / Глобальный выкуп</i>\n\n"
        f"🛡 <b>САППОРТЫ</b> ── {helper_1} | {helper_2}\n"
        f"  └─<i>Наставление / Прием материала</i>\n\n"
        f"⚙️ <b>АРХИТЕКТОР</b> ── {support_link2}\n"
        f"  └─<i>Технические вопросы / Бот </i>\n"
        f"{DIVIDER}\n"
        f"[🟢 <b>ONLINE</b>] ── <i>Отклик: ~15 MIN.</i>\n"
    )

    await callback.answer()
    
    if callback.message is not None:
        try:
            # Плавная замена на баннер саппорта
            msg = await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=get_seller_main_kb()
            )
            # Кэшируем file_id для мгновенной работы в будущем
            if isinstance(banner, FSInputFile):
                media.save_from_message(filename, msg)
        except Exception:
            # Фолбэк на текст, если что-то пошло не так (например, спам кнопки)
            await edit_message_text_safe(
                callback.message, 
                text, 
                reply_markup=get_seller_main_kb(), 
                parse_mode="HTML"
            )


@router.message(F.text.in_({"INFO", "Справка"}))
async def on_info_root(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    settings = get_settings()
    await send_clean_text_screen(
        trigger_message=message,
        text=_info_root_text(),
        key="seller:info",
        reply_markup=_info_root_keyboard(settings.brand_channel_url, settings.brand_chat_url),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_SELLER_MENU_INFO)
async def on_seller_menu_info(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    
    settings = get_settings()
    text = _info_root_text()
    keyboard = _info_root_keyboard(settings.brand_channel_url, settings.brand_chat_url)
    
    # Достаем картинку для главного раздела Инфо
    filename = "info.jpg"
    banner = media.get(filename)
    
    await callback.answer()
    
    try:
        msg = await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=keyboard
        )
        if isinstance(banner, FSInputFile):
            media.save_from_message(filename, msg)
    except Exception:
        pass


@router.callback_query(F.data == CB_SELLER_INFO_ROOT)
async def on_info_root_refresh(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
        
    settings = get_settings()
    text = _info_root_text()
    keyboard = _info_root_keyboard(settings.brand_channel_url, settings.brand_chat_url)
    
    # Здесь та же самая картинка, так как это возврат в корень Инфо
    filename = "info.jpg"
    banner = media.get(filename)
    
    await callback.answer()
    
    try:
        msg = await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=keyboard
        )
        if isinstance(banner, FSInputFile):
            media.save_from_message(filename, msg)
    except Exception:
        pass


@router.callback_query(F.data == CB_SELLER_INFO_FAQ)
async def on_info_faq(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    
    filename = "faq.jpg"
    banner = media.get(filename)
    
    text = (
        f"❖ <b>GDPX ACADEMY // БАЗА ЗНАНИЙ</b>\n"
        f"{DIVIDER}\n"
        f"Доступ к архивным протоколам разрешен.\n"
        f"Выберите директорию для изучения:\n\n"
        f"📡 <b>STATUS:</b> <code>UNDER ARCHITECT OVERWATCH</code>\n"
        f" ╰ <i>Архитектор мониторит фрод-алгоритм 24/7.</i>"
        f"{DIVIDER}"
    )
    
    await callback.answer()
    try:
        msg = await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=_faq_list_keyboard()
        )
        if isinstance(banner, FSInputFile):
            media.save_from_message(filename, msg)
    except Exception:
        pass


@router.callback_query(F.data == CB_SELLER_INFO_MANUALS)
async def on_info_manuals(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    
    filename = "baza.jpg"
    banner = media.get(filename)
    
    text = (
        f"❖ <b>GDPX ACADEMY // МАНУАЛЫ</b>\n"
        f"{DIVIDER}\n"
        f"Доступные уровни подготовки:\n\n"
        f"📡 <b>STATUS:</b> <code>READY</code>"
    )
    
    await callback.answer()
    try:
        msg = await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=_manuals_levels_keyboard()
        )
        if isinstance(banner, FSInputFile):
            media.save_from_message(filename, msg)
    except Exception:
        pass


@router.callback_query(F.data.startswith(f"{CB_SELLER_FAQ_OPEN}:"))
async def on_faq_open(callback: CallbackQuery) -> None:
    if callback.message is None or callback.data is None:
        return
    faq_id = callback.data.split(":")[3]
    card = get_faq_by_id(faq_id)
    if card is None:
        await callback.answer("FAQ не найден", show_alert=True)
        return
    
    filename = "faq.jpg" # Оставляем баннер FAQ для самих статей
    banner = media.get(filename)

    await callback.answer()
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
            reply_markup=_faq_detail_keyboard()
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith(f"{CB_SELLER_MANUAL_LEVEL}:"))
async def on_manual_level(callback: CallbackQuery) -> None:
    if callback.message is None or callback.data is None:
        return
    level_id = callback.data.split(":")[3]
    level = next((lvl for lvl in MANUAL_LEVELS if lvl.id == level_id), None)
    if level is None:
        await callback.answer("Уровень не найден", show_alert=True)
        return

    filename = "baza.jpg"
    banner = media.get(filename)
    
    text = (
        f"❖ <b>{level.emoji} {level.title}</b>\n"
        f"{DIVIDER}\n"
        f"<i>Выберите мануал:</i>"
    )

    await callback.answer()
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
            reply_markup=_manuals_level_keyboard(level_id)
        )
    except Exception:
        pass


#--- Opening Specific Manual ---
@router.callback_query(F.data.startswith(f"{CB_SELLER_MANUAL_OPEN}:"))
async def on_manual_open(callback: CallbackQuery) -> None:
    if callback.message is None or callback.data is None:
        return
    manual_id = callback.data.split(":")[3]
    card = get_manual_by_id(manual_id)
    if card is None:
        await callback.answer("Мануал не найден", show_alert=True)
        return

    filename = "baza.jpg"
    banner = media.get(filename)

    await callback.answer()
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=banner, caption=card.text, parse_mode="HTML"),
            reply_markup=_manual_detail_keyboard(card.level)
        )
    except Exception:
        pass
