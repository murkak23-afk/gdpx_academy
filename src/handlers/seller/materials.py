from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.utils.media import media
from src.keyboards.factory import SellerMenuCD, SellerAssetCD, SellerItemCD, NavCD
from src.keyboards.builders import get_seller_main_kb
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="seller-materials-router")
logger = logging.getLogger(__name__)

@router.callback_query(SellerMenuCD.filter(F.action == "assets"))
async def list_folders(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список категорий."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    folders = await SubmissionService(session=session).get_user_material_folders(user.id)

    if not folders:
        await callback.answer("📭 У вас пока нет загруженных товаров", show_alert=True)
        return

    rows = []
    for f in folders:
        text = f"{f['title']} ({f['total']})"
        rows.append([
            InlineKeyboardButton(text=text, callback_data=SellerAssetCD(category_id=f['category_id']).pack())
        ])
    
    rows.append([InlineKeyboardButton(text="❮ Назад", callback_data=NavCD(to="menu").pack())])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    
    banner = media.get("items.jpg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption="<b>Ваши активы по операторам:</b>", parse_mode="HTML"),
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(SellerAssetCD.filter())
async def list_items_in_category(callback: CallbackQuery, callback_data: SellerAssetCD, session: AsyncSession) -> None:
    """Список конкретных товаров."""
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    items, total = await SubmissionService(session=session).list_user_material_by_category_paginated(
        user_id=user.id,
        category_id=callback_data.category_id,
        page=callback_data.page,
        page_size=10,
        statuses=None # Фиксация ошибки: добавлен обязательный аргумент
    )

    if not items:
        await callback.answer("В этой категории пусто", show_alert=True)
        return

    rows = []
    for item in items:
        status_emoji = "🟠" if item.status == "pending" else "🟢" if item.status == "accepted" else "🔴"
        text = f"{status_emoji} ID:{item.id} | {item.description_text[:15]}..."
        rows.append([
            InlineKeyboardButton(text=text, callback_data=SellerItemCD(item_id=item.id, action="view").pack())
        ])
    
    rows.append([InlineKeyboardButton(text="❮ К папкам", callback_data=SellerMenuCD(action="assets").pack())])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    
    await edit_message_text_or_caption_safe(
        callback.message,
        f"<b>Товары в категории</b> (Всего: {total}):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(SellerItemCD.filter(F.action == "view"))
async def view_item(callback: CallbackQuery, callback_data: SellerItemCD, session: AsyncSession) -> None:
    """Детальный просмотр товара."""
    item = await SubmissionService(session=session).get_by_id(callback_data.item_id)
    if not item:
        await callback.answer("🔴 Товар не найден", show_alert=True)
        return

    text = (
        f"<b>Карточка товара #{item.id}</b>\n\n"
        f"Статус: {item.status}\n"
        f"Описание: {item.description_text}\n"
        f"Дата: {item.created_at.strftime('%Y-%m-%d %H:%M')}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=SellerItemCD(item_id=item.id, action="delete").pack())],
        [InlineKeyboardButton(text="❮ Назад", callback_data=SellerAssetCD(category_id=item.category_id).pack())]
    ])
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
