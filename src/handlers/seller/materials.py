"""
Премиум-раздел "Мои активы" (Личный кабинет селлера).
Статистика строго за сегодня по МСК, выделение лучших категорий, удобная пагинация.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from html import escape

from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.utils.media import media
from src.keyboards.factory import SellerMenuCD, SellerAssetCD, SellerItemCD
from src.keyboards.builders import get_seller_assets_folders_kb, get_seller_assets_items_kb, get_seller_item_view_kb
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="seller-materials-premium-router")
logger = logging.getLogger(__name__)

STATUS_MAP = {
    "all": ("Все симки", "📦"),
    "pending": ("Ожидает модерации", "⏳"),
    "in_review": ("В работе", "🟠"),
    "accepted": ("Зачтено", "🟢"),
    "rejected": ("Отклонено / Брак", "🔴"),
}


@router.callback_query(SellerMenuCD.filter(F.action == "assets"))
async def list_folders(callback: CallbackQuery, session: AsyncSession) -> None:
    """Главный дашборд 'Мои активы'."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_service = SubmissionService(session=session)

    daily_stats = await sub_service.get_daily_assets_stats(user.id)
    best_cat_id = await sub_service.get_best_category_for_user(user.id)
    folders = await sub_service.get_user_material_folders(user.id)

    total_earned = daily_stats["total_earned"]

    text = (
        f"❖ <b>GDPX // ВАШИ СИМКИ</b>\n"
        f"{DIVIDER}\n"
        f"📊 <b>СВОДКА ЗА СЕГОДНЯ</b> (с 00:00 МСК):\n"
        f" ├ 🟢 <b>Зачтено:</b> <code>{daily_stats['accepted']}</code> шт.\n"
        f" ├ ⏳ <b>В работе:</b> <code>{daily_stats['pending'] + daily_stats['in_review']}</code> шт.\n"
        f" ├ 🔴 <b>Брак:</b> <code>{daily_stats['rejected']}</code> шт.\n"
        f" └ 🪙 <b>Заработано сегодня:</b> <code>{total_earned:.2f}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"🗂 <b>КЛАСТЕРЫ С СИМКАМИ:</b>\n"
        f"<i>Выберите кластер для детального просмотра.</i>"
    )

    banner = media.get("items.jpg")

    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
        reply_markup=get_seller_assets_folders_kb(folders, best_cat_id)
    )
    await callback.answer()

    @router.callback_query(SellerAssetCD.filter(), StateFilter(None))
    async def list_items_in_category(callback: CallbackQuery, callback_data: SellerAssetCD, session: AsyncSession) -> None:
        """Список активов внутри выбранного кластера + фильтры."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_service = SubmissionService(session=session)

    status_filter = None
    if callback_data.filter_key != "all":
        from src.database.models.enums import SubmissionStatus
        status_mapping = {
            "pending": [SubmissionStatus.PENDING],
            "in_review": [SubmissionStatus.IN_REVIEW],
            "accepted": [SubmissionStatus.ACCEPTED],
            "rejected": [SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]
        }
        status_filter = status_mapping.get(callback_data.filter_key)

    items, total = await sub_service.list_user_material_by_category_paginated(
        user_id=user.id,
        category_id=callback_data.category_id,
        page=callback_data.page or 0,
        page_size=7,
        statuses=status_filter
    )

    # Получаем название категории
    cat_title = "Неизвестно"
    if items:
        cat_title = items[0].category.title
    else:
        from src.services.category_service import CategoryService
        cat = await CategoryService(session=session).get_by_id(callback_data.category_id)
        if cat:
            cat_title = cat.title

    filter_name, filter_emoji = STATUS_MAP.get(callback_data.filter_key or "all", ("Все активы", "📦"))

    text = (
        f"❖ <b>GDPX // АКТИВЫ КЛАСТЕРА</b>\n"
        f"{DIVIDER}\n"
        f"🗂 <b>{escape(cat_title)}</b>\n"
        f"🔍 <b>Фильтр:</b> {filter_emoji} {filter_name} (Всего: <code>{total}</code>)\n"
        f"{DIVIDER_LIGHT}\n"
    )

    if not items:
        text += "<i>По данному фильтру активов не найдено.</i>"

    await edit_message_text_or_caption_safe(
        callback.message,
        text=text,
        reply_markup=get_seller_assets_items_kb(items, callback_data.category_id, callback_data.page or 0, total, callback_data.filter_key or "all"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(SellerItemCD.filter(F.action == "view"), StateFilter(None))
async def view_item(callback: CallbackQuery, callback_data: SellerItemCD, session: AsyncSession) -> None:
    """Детальный просмотр одной eSIM (карточки актива)."""
    item = await SubmissionService(session=session).get_by_id(callback_data.item_id)
    if not item:
        await callback.answer("🔴 Симка не найдена", show_alert=True)
        return

    status_mapping = {
        "pending": ("⏳ ОЖИДАЕТ", "В буфере модерации"),
        "in_review": ("🟠 В РАБОТЕ", "Проходит дефектовку"),
        "accepted": ("🟢 ЗАЧТЕНО", "Готов к выплате"),
        "rejected": ("🔴 ОТКЛОНЕНО", "Брак"),
        "blocked": ("🔴 ЗАБЛОКИРОВАНО", "Грубое нарушение"),
        "not_a_scan": ("🔴 НЕ СКАН", "Неверный формат")
    }

    status_label, status_desc = status_mapping.get(item.status.value, ("▫️ " + item.status.value.upper(), ""))
    price = getattr(item, "fixed_payout_rate", "0.00")
    date_str = item.created_at.strftime('%d.%m.%Y %H:%M')

    text = (
        f"❖ <b>GDPX // ДЕТАЛИЗАЦИЯ АКТИВА</b>\n"
        f"{DIVIDER}\n"
        f"🔖 <b>ID Карточки:</b> <code>{item.id}</code>\n"
        f"🗂 <b>Кластер:</b> <code>{escape(item.category.title)}</code>\n"
        f"📅 <b>Загружен:</b> <code>{date_str}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"📉 <b>СТАТУС:</b> <b>{status_label}</b>\n"
        f"└ <i>{status_desc}</i>\n\n"
        f"🪙 <b>Стоимость выкупа:</b> <code>{price}</code> USDT\n"
    )

    if item.status.value in ["rejected", "blocked", "not_a_scan"] and getattr(item, "rejection_reason", None):
        text += f"\n📝 <b>ПРИЧИНА ОТКАЗА:</b> {item.rejection_reason.value}\n"
    if getattr(item, "rejection_comment", None):
        text += f"💬 <b>Комментарий:</b> {escape(item.rejection_comment)}\n"

    await edit_message_text_or_caption_safe(
        callback.message,
        text,
        reply_markup=get_seller_item_view_kb(item.id, item.category_id),
        parse_mode="HTML"
    )
    await callback.answer()