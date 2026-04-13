from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from .keyboards import get_seller_assets_folders_kb, get_seller_assets_items_kb, get_seller_item_view_kb
from src.presentation.common.factory import SellerAssetCD, SellerItemCD, SellerMenuCD
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.core.utils.media import media
from src.core.utils.text_format import edit_message_text_or_caption_safe
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.core.utils.message_manager import MessageManager

router = Router(name="seller-materials-premium-router")
logger = logging.getLogger(__name__)

STATUS_MAP = {
    "all": ("Все активы", "📦"),
    "pending": ("Ожидает модерации", "⏳"),
    "in_review": ("В работе", "🟠"),
    "accepted": ("Зачтено", "🟢"),
    "rejected": ("Отклонено / Брак", "🔴"),
}

@router.callback_query(SellerMenuCD.filter(F.action == "assets"), StateFilter(None))
async def list_folders(callback: CallbackQuery, session: AsyncSession, ui: MessageManager) -> None:
    """Главный дашборд 'Мои активы': статистика за СЕГОДНЯ и список кластеров (активные)."""
    # Очищаем уведомления при входе в материалы
    from src.presentation.common.notifications import clear_notifications
    await clear_notifications(callback.from_user.id, callback.bot)

    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    sub_service = SubmissionService(session=session)
    
    daily_stats = await sub_service.get_daily_assets_stats(user.id)
    best_cat_id = await sub_service.get_best_category_for_user(user.id)
    folders = await sub_service.get_user_material_folders(user.id, is_archived=False)

    total_earned = daily_stats["total_earned"]
    pending = daily_stats["pending"]
    in_review = daily_stats["in_review"]
    accepted = daily_stats["accepted"]
    rejected = daily_stats["rejected"]

    text = (
        f"❖ <b>GDPX // ВАШИ СИМКИ</b>\n"
        f"{DIVIDER}\n"
        f"📊 <b>СВОДКА ЗА СЕГОДНЯ</b> (с 00:00 МСК):\n"
        f" ├ 🟢 <b>Зачтено:</b> <code>{accepted}</code> шт.\n"
        f" ├ ⏳ <b>Ожидает:</b> <code>{pending + in_review}</code> шт.\n"
        f" ├ 🔴 <b>Брак:</b> <code>{rejected}</code> шт.\n"
        f" └ 💰 <b>Заработано:</b> <code>{total_earned:.2f}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"🗂 <b>ДОСТУПНЫЕ КЛАСТЕРЫ:</b>\n"
        f"<i>Выберите кластер для просмотра детализации.</i>"
    )
    
    banner = media.get("simki.jpg")
    
    if not folders:
        text += "\n\n📭 <i>Вы еще не интегрировали ни одного актива.</i>"
        
    await ui.display(event=callback, text=text, reply_markup=await get_seller_assets_folders_kb(folders, best_cat_id, is_archived=False), photo=banner)
    await callback.answer()


@router.callback_query(SellerAssetCD.filter(), StateFilter(None))
async def list_items_in_category(callback: CallbackQuery, callback_data: SellerAssetCD, session: AsyncSession) -> None:
    """Интерфейс активов внутри конкретного кластера с фильтрами."""
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
        statuses=status_filter,
        is_archived=callback_data.is_archived
    )
    
    cat_title = "Неизвестно"
    from src.domain.submission.category_service import CategoryService
    cat = await CategoryService(session=session).get_by_id(callback_data.category_id)
    if cat: 
        cat_title = cat.title

    filter_name, filter_emoji = STATUS_MAP.get(callback_data.filter_key or "all", ("Все симки", "📦"))

    text = (
        f"❖ <b>GDPX // ОПЕРАТОР</b>\n"
        f"{DIVIDER}\n"
        f"🗂 <b>{escape(cat_title)}</b>"
    )
    
    if callback_data.is_archived:
        text += " (АРХИВ)"
        
    text += (
        f"\n🔍 <b>Фильтр:</b> {filter_emoji} {filter_name} (Всего: <code>{total}</code>)\n"
        f"{DIVIDER_LIGHT}\n"
    )
    
    if not items:
        text += "<i>По данному фильтру активов не найдено.</i>"

    await edit_message_text_or_caption_safe(
        callback.message,
        text=text,
        reply_markup=await get_seller_assets_items_kb(
            items, 
            callback_data.category_id, 
            callback_data.page or 0, 
            total, 
            callback_data.filter_key or "all",
            is_archived=callback_data.is_archived
        ),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(SellerItemCD.filter(F.action == "view"), StateFilter(None))
async def view_item(callback: CallbackQuery, callback_data: SellerItemCD, session: AsyncSession) -> None:
    """Детальный премиум-просмотр одной карточки eSIM с 4-значным идентификатором."""
    item = await SubmissionService(session=session).get_by_id(callback_data.item_id)
    if not item:
        await callback.answer("🔴 Актив не найден", show_alert=True)
        return

    from src.domain.submission.category_service import CategoryService
    cat = await CategoryService(session=session).get_by_id(item.category_id)
    cat_title = cat.title if cat else "Неизвестно"

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
    
    # Логика идентификатора номера
    phone = item.phone_normalized
    ident = f"...{phone[-4:]}" if phone and len(phone) >= 4 else f"#{item.id}"
    phone_display = f"+{phone}" if phone else "Не распознан"

    text = (
        f"❖ <b>GDPX // ДЕТАЛИЗАЦИЯ АКТИВА</b>\n"
        f"{DIVIDER}\n"
        f"🔖 <b>Идентификатор:</b> <code>{ident}</code>\n"
        f"📞 <b>Полный номер:</b> <code>{escape(phone_display)}</code>\n"
        f"🗂 <b>Кластер:</b> <code>{escape(cat_title)}</code>\n"
        f"📅 <b>Загружен:</b> <code>{date_str}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"📉 <b>СТАТУС:</b> <b>{status_label}</b>\n"
        f"└ <i>{status_desc}</i>\n\n"
        f"💰 <b>Зафиксированная ставка:</b> <code>{price}</code> USDT\n"
    )

    if item.status.value in ["rejected", "blocked", "not_a_scan"] and item.rejection_reason:
        text += f"\n⚠️ <b>ПРИЧИНА ОТКАЗА:</b> {item.rejection_reason}\n"
        if item.rejection_comment:
            text += f"💬 <b>Комментарий:</b> {escape(item.rejection_comment)}\n"

    await edit_message_text_or_caption_safe(
        callback.message, 
        text, 
        reply_markup=await get_seller_item_view_kb(item.id, item.category_id, item.status.value), 
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(SellerItemCD.filter(F.action == "delete"), StateFilter(None))
async def delete_item_confirm(callback: CallbackQuery, callback_data: SellerItemCD, session: AsyncSession) -> None:
    """Отзыв (удаление) актива селлером."""
    try:
        user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        sub_svc = SubmissionService(session=session)

        success, message = await sub_svc.delete_submission(callback_data.item_id, user.id)
        if success:
            await session.commit()
            await callback.answer("✅ Актив успешно отозван", show_alert=True)
            # Возвращаемся к списку кластеров (так проще, чем обновлять список)
            await list_folders(callback, session)
        else:
            await callback.answer(f"❌ Ошибка: {message}", show_alert=True)

    except Exception as e:
        logger.exception(f"Error in delete_item_confirm: {e}")
        await callback.answer("⚠️ Произошла ошибка при отзыве актива", show_alert=True)

@router.callback_query(F.data.startswith("sel_asset_pg"), StateFilter(None))
async def process_asset_pagination(callback: CallbackQuery, session: AsyncSession):
    """Обработка переключения страниц в списке активов (поддержка архива)."""
    try:
        # Формат: sel_asset_pg:p:PAGE:CAT_ID:FILTER:ARCHIVE
        parts = callback.data.split(":")
        if len(parts) < 4:
            return await callback.answer()

        _, action, page, query = parts
        query_parts = query.split(":")

        if len(query_parts) == 3:
            cat_id, filter_key, archive_flag = query_parts
            is_archived = archive_flag == "1"
        else:
            # Обратная совместимость для старых кнопок (без флага архива)
            cat_id, filter_key = query_parts
            is_archived = False

        callback_data = SellerAssetCD(
            category_id=int(cat_id),
            page=int(page),
            filter_key=filter_key,
            is_archived=is_archived
        )
        await list_items_in_category(callback, callback_data, session)
    except Exception as e:
        logger.exception(f"Pagination error: {e}")
        await callback.answer("⚠️ Ошибка навигации", show_alert=True)