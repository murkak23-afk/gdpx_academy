from __future__ import annotations

import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.category_service import CategoryService
from src.services.submission_service import SubmissionService
from src.services.user_service import UserService
from src.utils.media import media
from src.states.submission_state import SubmissionState
from src.keyboards.factory import SellerMenuCD, SellerAssetCD, NavCD
from src.keyboards.builders import get_seller_main_kb, get_categories_kb
from src.utils.ui_builder import DIVIDER
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="seller-submission-router")
logger = logging.getLogger(__name__)

# --- Универсальный хедер для eSIM ---
SUBMISSION_HEADER = (
    f"❖ <b>GDPX // ПРОДАТЬ eSIM</b>\n"
    f"{DIVIDER}\n"
    f"STEPS 1/3 ✦ ВЫБОР ОПЕРАТОРА\n"
    f"            2/3 ✦ ЗАГРУЗКА ФОТО\n"
    f"             3/3 ✦ НОМЕР ТЕЛЕФОНА\n"
    f"⛩ Искусный сокол прячет когти!  🦅\n"
    f"{DIVIDER}"
)

@router.callback_query(SellerMenuCD.filter(F.action == "sell"))
async def start_submission(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Шаг 1: Выбор категории."""
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("🔴 Нет активных категорий", show_alert=True)
        return
    
    await state.set_state(SubmissionState.waiting_for_category)
    banner = media.get("esim.jpg")
    
    await callback.message.edit_media(
        media=InputMediaPhoto(media=banner, caption=SUBMISSION_HEADER, parse_mode="HTML"),
        reply_markup=get_categories_kb(categories)
    )
    await callback.answer()

@router.callback_query(SellerAssetCD.filter(), StateFilter(SubmissionState.waiting_for_category))
async def pick_category(callback: CallbackQuery, callback_data: SellerAssetCD, state: FSMContext, session: AsyncSession) -> None:
    """Шаг 2: Ожидание фото."""
    category = await CategoryService(session=session).get_by_id(callback_data.category_id)
    if not category:
        await callback.answer("🔴 Категория не найдена", show_alert=True)
        return
    
    await state.update_data(category_id=category.id)
    await state.set_state(SubmissionState.waiting_for_photo)
    
    text = f"{SUBMISSION_HEADER}\n\n📥 <b>ШАГ 2:</b> Отправьте фото QR-кода или скриншот eSIM."
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Отменить", callback_data=NavCD(to="menu").pack())]
    ])
    
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=cancel_kb)
    await callback.answer(f"Выбрано: {category.title}")

@router.message(SubmissionState.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Шаг 3: Ожидание описания (номера)."""
    photo = message.photo[-1]
    await state.update_data(photo_id=photo.file_id, file_unique_id=photo.file_unique_id)
    await state.set_state(SubmissionState.waiting_for_description)
    
    text = f"{SUBMISSION_HEADER}\n\n📱 <b>ШАГ 3:</b> Введите номер телефона eSIM ответным сообщением."
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Отменить", callback_data=NavCD(to="menu").pack())]
    ])
    
    await message.answer(text, reply_markup=cancel_kb, parse_mode="HTML")

@router.message(SubmissionState.waiting_for_description, F.text)
async def process_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Финиш: Сохранение eSIM."""
    data = await state.get_data()
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    
    submission = await SubmissionService(session=session).create_submission(
        user_id=user.id,
        category_id=data['category_id'],
        telegram_file_id=data['photo_id'],
        file_unique_id=data['file_unique_id'],
        image_sha256="legacy_skip",
        description_text=message.text,
    )
    
    await session.commit()
    await state.clear()
    
    await message.answer(
        f"🟢 <b>УСПЕШНО!</b>\nЗаявка #{submission.id} принята в обработку.",
        reply_markup=get_seller_main_kb(),
        parse_mode="HTML"
    )
