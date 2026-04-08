"""
Премиум-загрузка активов (eSIM) селлером.
Особенности: Bulk-операции в FSM, Debounce-таймер UI, строгая фиксация ставки.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.category_service import CategoryService
from src.services.submission_service import SubmissionService
from src.services.user_service import UserService
from src.utils.media import media
from src.states.submission_state import SubmissionState
from src.keyboards.factory import SellerMenuCD, SellerAssetCD
from src.keyboards import get_seller_main_kb, get_categories_kb, get_upload_finish_kb
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="seller-submission-premium-router")
logger = logging.getLogger(__name__)

# Хранилище задач для debounce
_debounce_tasks: dict[int, asyncio.Task] = {}


def _get_upload_header() -> str:
    return (
        f"❖ <b>GDPX // ИНТЕГРАЦИЯ АКТИВОВ</b>\n"
        f"{DIVIDER}\n"
    )


@router.callback_query(SellerMenuCD.filter(F.action == "sell"))
async def start_submission(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Шаг 1: Выбор оператора."""
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("🔴 Нет активных операторов для загрузки", show_alert=True)
        return

    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    fav_ids = user.favorite_categories or []

    await state.set_state(SubmissionState.waiting_for_category)
    banner = media.get("esim.jpg")

    text = (
        f"{_get_upload_header()}"
        f"<b>ШАГ 1/2 ✦ ВЫБОР ОПЕРАТОРА</b>\n\n"
        f"Выберите целевого оператора для интеграции активов.\n"
        f"<i>⚠️ Ставка выкупа (USDT) фиксируется в момент загрузки и защищена от изменений.</i>"
    )

    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
        reply_markup=get_categories_kb(categories, fav_ids)
    )
    await callback.answer()


@router.callback_query(SellerAssetCD.filter(), StateFilter(SubmissionState.waiting_for_category))
async def pick_category(callback: CallbackQuery, callback_data: SellerAssetCD, state: FSMContext, session: AsyncSession) -> None:
    """Шаг 2: Открытие буфера загрузки."""
    category = await CategoryService(session=session).get_by_id(callback_data.category_id)
    if not category:
        await callback.answer("🔴 Оператор не найден", show_alert=True)
        return

    await state.update_data(
        category_id=category.id,
        category_title=category.title,
        fixed_payout_rate=str(category.payout_rate),
        media_pool=[]
    )
    await state.set_state(SubmissionState.waiting_for_media)

    text = (
        f"{_get_upload_header()}"
        f"🗂 <b>Выбран оператор:</b> <code>{escape(category.title)}</code>\n"
        f"🪙 <b>Стоимость выкупа:</b> <code>{category.payout_rate}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"📦 <b>БУФЕР СИМОК:</b> <code>0</code> шт.\n\n"
        f"💾 <b>Отправьте QR-Code, документы или ZIP-архивы.</b>\n"
        f"<i>Можно выделить до 50 файлов разом. После загрузки нажмите «Подтвердить интеграцию».</i>"
    )

    await edit_message_text_or_caption_safe(
        callback.message, text, reply_markup=get_upload_finish_kb(), parse_mode="HTML"
    )
    await state.update_data(status_msg_id=callback.message.message_id)
    await callback.answer("Приемник открыт. Жду файлы.")


async def _update_status_msg(user_id: int, bot: Bot, state: FSMContext, chat_id: int) -> None:
    """Debounce: обновляет счётчик загруженных файлов в UI."""
    await asyncio.sleep(0.3)  # 600ms debounce
    _debounce_tasks.pop(user_id, None)

    data = await state.get_data()
    pool = data.get("media_pool", [])
    msg_id = data.get("status_msg_id")
    payout_rate = Decimal(data.get("fixed_payout_rate", "0"))
    cat_title = data.get("category_title", "Unknown")

    if not msg_id or not pool:
        return

    count = len(pool)
    total_val = payout_rate * count

    text = (
        f"{_get_upload_header()}"
        f"🗂 <b>Оператор:</b> <code>{escape(cat_title)}</code>\n"
        f"🪙 <b>Ставка:</b> <code>{payout_rate}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"📦 <b>СИМОК В БУФЕРЕ:</b> <code>{count}</code> шт.\n"
        f"💎 <b>ОЖИДАЕМАЯ ЦЕННОСТЬ:</b> <code>{total_val:.2f}</code> USDT\n\n"
        f"<i>Отправьте еще файлы или нажмите «Подтвердить интеграцию».</i>"
    )

    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=msg_id,
            caption=text,
            reply_markup=get_upload_finish_kb(),
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.message(StateFilter(SubmissionState.waiting_for_media), F.photo | F.document | F.video)
async def process_bulk_media(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обработка входящих файлов в буфер."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await state.get_data()

    pool = data.get("media_pool", [])

    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        unique_id = photo.file_unique_id
        att_type = "photo"
    elif message.document:
        doc = message.document
        file_id = doc.file_id
        unique_id = doc.file_unique_id
        att_type = "document"
    else:
        vid = message.video
        file_id = vid.file_id
        unique_id = vid.file_unique_id
        att_type = "video"

    pool.append({
        "file_id": file_id,
        "unique_id": unique_id,
        "type": att_type,
        "caption": message.caption or ""
    })

    await state.update_data(media_pool=pool)

    # Перезапускаем debounce
    if user_id in _debounce_tasks:
        _debounce_tasks[user_id].cancel()

    _debounce_tasks[user_id] = asyncio.create_task(
        _update_status_msg(user_id, bot, state, chat_id)
    )

    # Удаляем сообщение пользователя, чтобы чат оставался чистым
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "upload_finish", StateFilter(SubmissionState.waiting_for_media))
async def finalize_upload(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """Финальное сохранение всех файлов."""
    data = await state.get_data()
    pool = data.get("media_pool", [])
    cat_id = data.get("category_id")
    payout_rate = Decimal(data.get("fixed_payout_rate", "0"))
    cat_title = data.get("category_title", "Unknown")

    if not pool or not cat_id:
        await callback.answer("🔴 Буфер пуст. Сначала отправьте файлы.", show_alert=True)
        return

    await callback.answer("⏳ Сохраняю активы...")

    loading_text = f"🔄 <b>БЕЗОПАСНАЯ ЗАПИСЬ...</b>\nСохраняем {len(pool)} активов..."
    await edit_message_text_or_caption_safe(callback.message, loading_text, parse_mode="HTML")

    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)

    try:
        await SubmissionService(session=session).create_bulk_submissions(
            user_id=user.id,
            category_id=cat_id,
            fixed_payout_rate=payout_rate,
            media_items=pool
        )
        await session.commit()

        total_val = len(pool) * payout_rate
        success_text = (
            f"🟢 <b>ИНТЕГРАЦИЯ УСПЕШНА</b>\n"
            f"{DIVIDER}\n"
            f"🗂 <b>Оператор:</b> <code>{escape(cat_title)}</code>\n"
            f"📦 <b>Загружено:</b> <code>{len(pool)}</code> шт.\n"
            f"💎 <b>Ожидаемая ценность:</b> <code>{total_val:.2f}</code> USDT\n\n"
            f"<i>Активы переданы в буфер модерации.</i>"
        )

        await state.clear()
        await edit_message_text_or_caption_safe(
            callback.message, success_text, reply_markup=get_seller_main_kb(), parse_mode="HTML"
        )

            # Уведомление админам
        try:
            asyncio.create_task(
                _notify_admins_about_upload(bot, user.telegram_id, len(pool), cat_title)
        )
        except Exception as e:
                logger.error(f"Failed to create admin notification task: {e}")

    except Exception as e:
        logger.error(f"Critical error during bulk insert: {e}", exc_info=True)
        await session.rollback()
        await edit_message_text_or_caption_safe(
            callback.message,
            "🔴 <b>КРИТИЧЕСКАЯ ОШИБКА</b>\nТранзакция отменена. Обратитесь в поддержку.",
            reply_markup=get_seller_main_kb(),
            parse_mode="HTML"
        )
        await state.clear()


@router.callback_query(F.data == "upload_cancel", StateFilter(SubmissionState.waiting_for_media))
async def cancel_upload(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена загрузки."""
    await state.clear()
    text = (
        f"❌ <b>ИНТЕГРАЦИЯ ОТМЕНЕНА</b>\n"
        f"{DIVIDER}\n"
        f"Буфер очищен. Несохранённые файлы удалены."
    )
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_seller_main_kb(), parse_mode="HTML")
    await callback.answer()


async def _notify_admins_about_upload(bot: Bot, seller_tg_id: int, count: int, cat_title: str) -> None:
    """Отправка алертов админам."""
    from src.core.config import get_settings
    admin_ids = get_settings().admin_telegram_ids
    if not admin_ids:
        return

    text = (
        f"🔔 <b>НОВЫЙ ЗАЛИВ АКТИВОВ</b>\n"
        f"Селлер: <a href='tg://user?id={seller_tg_id}'>ID {seller_tg_id}</a>\n"
        f"Кластер: <code>{escape(cat_title)}</code>\n"
        f"Объём: <code>{count}</code> шт.\n\n"
        f"<i>Ожидают модерации.</i>"
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")