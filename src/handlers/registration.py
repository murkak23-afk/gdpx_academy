from __future__ import annotations

import logging
import re
from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.submission_service import SubmissionService
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer
from src.keyboards import get_seller_main_kb
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import NavCD
from src.database.models.enums import UserLanguage
from src.states.registration_state import RegistrationState

router = Router(name="registration-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# --- Вспомогательные функции ---

async def _show_main_dashboard(target: Message | CallbackQuery, user, session: AsyncSession):
    """Вспомогательная функция для отрисовки дашборда с учетом статуса кодекса."""
    dashboard_stats = await SubmissionService(session=session).get_user_dashboard_stats(user.id)
    
    render_data = {
        "username": user.pseudonym or user.username or "resident",
        "telegram_id": user.telegram_id,
        "approved_count": int(dashboard_stats.get("accepted", 0)),
        "pending_count": int(dashboard_stats.get("pending", 0)),
        "in_review_count": 0,
        "rejected_count": int(dashboard_stats.get("rejected", 0)),
        "total_payout_amount": float(user.total_paid or 0),
    }
    
    text = _renderer.render_dashboard(render_data)
    banner = media.get("main.jpg")
    
    # Проверяем, принял ли пользователь кодекс
    has_accepted = getattr(user, "has_accepted_codex", False)
    reply_markup = get_seller_main_kb(has_accepted_codex=has_accepted)
    
    if isinstance(target, Message):
        await target.answer_photo(
            photo=banner,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        try:
            await target.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text),
                reply_markup=reply_markup
            )
        except Exception:
            await target.message.answer_photo(photo=banner, caption=text, reply_markup=reply_markup)
            await target.message.delete()

# --- Хендлеры регистрации ---

@router.message(CommandStart(), StateFilter(None))
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Точка входа: проверка регистрации или запуск FSM."""
    await state.clear()
    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(message.from_user.id)
    
    if user:
        await _show_main_dashboard(message, user, session)
        return

    # Если пользователя нет в базе — начинаем регистрацию
    kb = (PremiumBuilder()
          .button("🇷🇺 Русский", "lang:ru")
          .button("🇺🇸 English", "lang:en")
          .adjust(2)
          .as_markup())
    
    await message.answer(
        "🏮 <b>WELCOME // GDPX SYSTEM</b>\n"
        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
        "Выберите язык интерфейса для инициализации терминала.\n"
        "<i>Select interface language to initialize the terminal.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(RegistrationState.waiting_for_language)

@router.callback_query(RegistrationState.waiting_for_language, F.data.startswith("lang:"))
async def process_language(callback: CallbackQuery, state: FSMContext):
    """Выбор языка и переход к вводу псевдонима."""
    lang_code = callback.data.split(":")[1]
    lang = UserLanguage.RU if lang_code == "ru" else UserLanguage.EN
    await state.update_data(language=lang)
    
    from src.lexicon.ru import Lex # Импортируем для подсказки
    await callback.message.edit_text(Lex.ASK_PSEUDONYM, parse_mode="HTML")
    await state.set_state(RegistrationState.waiting_for_pseudonym)
    await callback.answer()

@router.message(RegistrationState.waiting_for_pseudonym)
async def process_pseudonym(message: Message, session: AsyncSession, state: FSMContext):
    """Валидация псевдонима и создание пользователя."""
    pseudonym = message.text.strip()
    
    if not re.match(r'^[a-zA-Z0-9_-]{2,32}$', pseudonym):
        await message.answer(
            "✖ <b>INVALID IDENTITY</b>\n"
            "Псевдоним должен содержать от 2 до 32 символов (латиница, цифры, _ или -).",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    user_service = UserService(session=session)
    
    # Проверка на уникальность (опционально, но желательно)
    # Здесь мы просто создаем пользователя
    user = await user_service.register_seller(
        tg_user=message.from_user,
        language=data['language'],
    )
    user.pseudonym = pseudonym
    await session.flush()
    
    await state.clear()
    await message.answer("✅ <b>IDENTITY FIXED</b>\nРегистрация в системе завершена.", parse_mode="HTML")
    await _show_main_dashboard(message, user, session)

@router.callback_query(NavCD.filter(F.to == "menu"))
async def back_to_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Возврат в меню через колбэк."""
    await state.clear()
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user:
        await _show_main_dashboard(callback, user, session)
    await callback.answer()
