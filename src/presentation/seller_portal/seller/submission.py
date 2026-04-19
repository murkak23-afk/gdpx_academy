"""
Премиум-загрузка активов (eSIM) селлером. Оптимизировано для сверхвысоких нагрузок.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

from .keyboards import get_categories_kb, get_seller_main_kb, get_upload_finish_kb
from src.presentation.common.factory import SellerAssetCD, SellerMenuCD
from src.domain.submission.category_service import CategoryService
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.domain.submission.submission_state import SubmissionState
from src.core.utils.media import media
from src.core.utils.text_format import delete_message_safe, edit_message_text_or_caption_safe
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.core.utils.message_manager import MessageManager

router = Router(name="seller-submission-premium-router")
logger = logging.getLogger(__name__)

# Хранилище задач для debounce (user_id -> Task)
_debounce_tasks: dict[int, asyncio.Task] = {}
# Локальный буфер (user_id -> {items: [], cat_title: str, payout: Decimal, msg_id: int})
_media_buffer: dict[int, dict] = {}


def _get_upload_header() -> str:
    return f"❖ <b>GDPX // ЗАЛЕЙ МАТЕРИАЛ</b>\n{DIVIDER}\n"


@router.message(Command("sell"))
@router.callback_query(SellerMenuCD.filter(F.action == "sell"))
async def start_submission(event: Message | CallbackQuery, state: FSMContext, session: AsyncSession, ui: MessageManager) -> None:
    """Шаг 1: Выбор оператора."""
    user_id = event.from_user.id
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        msg = "🔴 Нет активных операторов для загрузки"
        from src.presentation.seller_portal.seller.keyboards import get_seller_main_kb
        if isinstance(event, CallbackQuery): 
            await event.answer(msg, show_alert=True)
        else: 
            await event.answer(msg)
        await ui.display(event=event, text=f"❌ {msg}\nВозврат в главное меню.", reply_markup=await get_seller_main_kb())
        return

    user = await UserService(session=session).get_by_telegram_id(user_id)
    fav_ids = user.favorite_categories or []

    await state.set_state(SubmissionState.waiting_for_category)
    banner = media.get("esim.png")

    text = (
        f"{_get_upload_header()}"
        f"<b>ШАГ 1/2 ✦ ВЫБОР ОПЕРАТОРА</b>\n\n"
        f"Выберите целевого оператора для интеграции активов.\n"
        f"<i>⚠️ Ставка выкупа (USDT) фиксируется в момент загрузки и защищена от изменений.</i>"
    )

    kb = await get_categories_kb(categories, fav_ids)
    await ui.display(event=event, text=text, reply_markup=kb, photo=banner)
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(SellerAssetCD.filter(), StateFilter(SubmissionState.waiting_for_category))
async def pick_category(callback: CallbackQuery, callback_data: SellerAssetCD, state: FSMContext, session: AsyncSession, ui: MessageManager) -> None:
    """Шаг 2: Инициализация буфера загрузки."""
    category = await CategoryService(session=session).get_by_id(callback_data.category_id)
    if not category:
        return await callback.answer("🔴 Оператор не найден", show_alert=True)

    user_id = callback.from_user.id
    _media_buffer[user_id] = {
        "items": [],
        "cat_title": category.title,
        "payout": category.payout_rate,
        "msg_id": callback.message.message_id
    }

    await state.update_data(
        category_id=category.id,
        category_title=category.title,
        fixed_payout_rate=str(category.payout_rate),
        media_pool=[],
        status_msg_id=callback.message.message_id
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

    await ui.display(event=callback, text=text, reply_markup=await get_upload_finish_kb())
    await callback.answer("Приемник открыт")


async def _flush_buffer_to_state(user_id: int, state: FSMContext) -> int:
    """Переносит локальный буфер в FSM одним запросом."""
    buf = _media_buffer.get(user_id)
    if not buf or not buf["items"]:
        data = await state.get_data()
        return len(data.get("media_pool", []))
    
    items = buf.pop("items")
    buf["items"] = [] # Очищаем
    
    data = await state.get_data()
    pool = data.get("media_pool", [])
    pool.extend(items)
    await state.update_data(media_pool=pool)
    return len(pool)


@router.message(StateFilter(SubmissionState.waiting_for_media), F.photo | F.document | F.video)
async def process_bulk_media(message: Message, state: FSMContext, bot: Bot, ui: MessageManager) -> None:
    """Сверхскоростная обработка файлов (In-Memory Buffering)."""
    user_id = message.from_user.id
    
    file = message.photo[-1] if message.photo else (message.document or message.video)
    m_type = "photo" if message.photo else ("document" if message.document else "video")
    
    item = {"file_id": file.file_id, "unique_id": file.file_unique_id, "type": m_type, "caption": message.caption or ""}

    if user_id not in _media_buffer:
        _media_buffer[user_id] = {"items": [], "cat_title": "...", "payout": Decimal("0"), "msg_id": 0}
    
    _media_buffer[user_id]["items"].append(item)
    asyncio.create_task(delete_message_safe(message))

    if user_id in _debounce_tasks: _debounce_tasks[user_id].cancel()
    _debounce_tasks[user_id] = asyncio.create_task(_refresh_control_panel(user_id, bot, state, message.chat.id, ui))


async def _refresh_control_panel(user_id: int, bot: Bot, state: FSMContext, chat_id: int, ui: MessageManager) -> None:
    """Тихое обновление UI без лишних обращений к Redis."""
    await asyncio.sleep(0.3) 
    
    buf = _media_buffer.get(user_id)
    if not buf: return

    count = await _flush_buffer_to_state(user_id, state)
    msg_id = buf["msg_id"]
    
    if not msg_id:
        data = await state.get_data()
        msg_id = data.get("status_msg_id")
        buf["msg_id"] = msg_id

    if not msg_id: return

    text = (
        f"{_get_upload_header()}"
        f"🗂 <b>Оператор:</b> <code>{escape(buf['cat_title'])}</code>\n"
        f"📦 <b>В БУФЕРЕ:</b> <code>{count}</code> шт.\n"
        f"{DIVIDER_LIGHT}\n"
        f"📥 <b>Продолжайте отправку...</b>\n"
        f"<i>Нажмите «Подтвердить интеграцию» для сохранения.</i>"
    )

    try:
        # Для дебаунса используем прямой edit или ui.display?
        # ui.display удалит и пришлет новое если edit упадет, что нам и нужно
        # Но нам нужен объект "Update" или "Message" чтобы вызвать ui.display
        # Костыль: передаем пустой Message(id=msg_id)
        from aiogram.types import User, Chat
        dummy = Message(message_id=msg_id, date=datetime.now(), chat=Chat(id=user_id, type="private"), from_user=User(id=user_id, is_bot=False, first_name="..."))
        await ui.display(event=dummy, text=text, reply_markup=await get_upload_finish_kb())
    except Exception as e:
        logger.debug(f"Debounce display failed: {e}")
    _debounce_tasks.pop(user_id, None)


@router.callback_query(F.data == "upload_finish", StateFilter(SubmissionState.waiting_for_media))
async def finalize_upload(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot, ui: MessageManager, **data_extra) -> None:
    """Финальное сохранение пачки в БД."""
    user_id = callback.from_user.id
    await _flush_buffer_to_state(user_id, state)
    
    data = await state.get_data()
    pool, cat_id = data.get("media_pool", []), data.get("category_id")
    rate, title = Decimal(data.get("fixed_payout_rate", "0")), data.get("category_title", "Unknown")

    if not pool or not cat_id:
        return await callback.answer("🔴 Буфер пуст", show_alert=True)

    await callback.answer("💾 Сохранение...")
    await ui.display(event=callback, text="🔄 <b>ЗАПИСЬ В СИСТЕМУ...</b>")

    user = await UserService(session=session).get_by_telegram_id(user_id)
    try:
        created = await SubmissionService(session=session).create_bulk_submissions(user_id=user.id, category_id=cat_id, fixed_payout_rate=rate, media_items=pool)
        await session.commit()
        ws_manager = data_extra.get("ws_manager") or bot.get("ws_manager")
        if ws_manager:
            await ws_manager.broadcast({
                "type": "notification",
                "message": f"🏮 НОВАЯ ПОСТАВКА: {len(created)} шт. {title}",
                "style": "success"
            })
        await state.clear()
        await ui.display(event=callback, text=f"✅ <b>Принято {len(created)} симок.</b>", reply_markup=await get_seller_main_kb())
        asyncio.create_task(_notify_admins_about_upload(bot, user.telegram_id, len(created), title))
    except Exception as e:
        logger.error(f"Bulk insert failed: {e}", exc_info=True)
        await session.rollback()
        await ui.display(event=callback, text="❌ <b>ОШИБКА ЗАПИСИ</b>", reply_markup=await get_seller_main_kb())
        await state.clear()
    finally:
        _media_buffer.pop(user_id, None)
        task = _debounce_tasks.pop(user_id, None)
        if task:
            task.cancel()


@router.callback_query(F.data == "upload_cancel", StateFilter(SubmissionState.waiting_for_media))
async def cancel_upload(callback: CallbackQuery, state: FSMContext, ui: MessageManager) -> None:
    """Отмена загрузки."""
    _media_buffer.pop(callback.from_user.id, None)
    await state.clear()
    await ui.display(event=callback, text=f"❌ <b>ИНТЕГРАЦИЯ ОТМЕНЕНА</b>\n{DIVIDER}\nБуфер очищен.", reply_markup=await get_seller_main_kb())
    await callback.answer()


async def _notify_admins_about_upload(bot: Bot, seller_tg_id: int, count: int, cat_title: str) -> None:
    """Отправка алертов админам (фоново)."""
    from src.core.config import get_settings
    admin_ids = get_settings().admin_telegram_ids
    if not admin_ids: return
    text = f"🔔 <b>НОВЫЙ ЗАЛИВ QR-CODE</b>\nСеллер: <a href='tg://user?id={seller_tg_id}'>ID {seller_tg_id}</a>\nКластер: <code>{escape(cat_title)}</code>\nОбъём: <code>{count}</code> шт.\n\n<i>Ожидают модерации.</i>"
    for admin_id in admin_ids:
        try: await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except Exception: pass
