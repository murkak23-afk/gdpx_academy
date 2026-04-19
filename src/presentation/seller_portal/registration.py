from __future__ import annotations

import logging
import re

from aiogram import F, Router, Bot
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.utils.message_manager import MessageManager

from src.database.models.enums import UserLanguage
from .seller.keyboards import get_seller_main_kb
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import NavCD
from src.domain.submission.submission_service import SubmissionService
from src.domain.users.user_service import UserService
from src.domain.users.registration_state import RegistrationState
from src.core.utils.media import media
from src.core.utils.ui_builder import GDPXRenderer

router = Router(name="registration-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

# --- Вспомогательные функции ---

async def _show_main_dashboard(target: Message | CallbackQuery, user, session: AsyncSession, ui: MessageManager):
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
    reply_markup = await get_seller_main_kb(has_accepted_codex=has_accepted)
    
    await ui.display(event=target, text=text, reply_markup=reply_markup, photo=banner)

# --- Хендлеры регистрации ---

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager) -> None:
    """Точка входа: проверка регистрации или запуск FSM."""
    await state.clear()
    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(message.from_user.id)
    
    if user:
        await _show_main_dashboard(message, user, session, ui)
        return

    # Если пользователя нет в базе — начинаем регистрацию
    kb = (PremiumBuilder()
          .button("🇷🇺 Русский", "lang:ru")
          .button("🇺🇸 English", "lang:en")
          .adjust(2)
          .as_markup())
    
    await ui.display(
        event=message,
        text=(
            "<b>WELCOME // GDPX SYSTEM</b>\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "Выберите язык интерфейса для инициализации терминала.\n"
            "<i>Select interface language to initialize the terminal.</i>"
        ),
        reply_markup=kb,
    )
    await state.set_state(RegistrationState.waiting_for_language)

@router.callback_query(RegistrationState.waiting_for_language, F.data.startswith("lang:"))
async def process_language(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Выбор языка и переход к вводу псевдонима."""
    lang_code = callback.data.split(":")[1]
    lang = UserLanguage.RU if lang_code == "ru" else UserLanguage.EN
    await state.update_data(language=lang)
    
    from src.presentation.lexicon.ru import Lex  # Импортируем для подсказки
    await ui.display(event=callback, text=Lex.ASK_PSEUDONYM)
    await state.set_state(RegistrationState.waiting_for_pseudonym)
    await callback.answer()

@router.message(RegistrationState.waiting_for_pseudonym)
async def process_pseudonym(message: Message, session: AsyncSession, state: FSMContext, ui: MessageManager):
    """Валидация псевдонима и переход к FAQ."""
    pseudonym = message.text.strip()
    
    if not re.match(r'^[a-zA-Z0-9_-]{2,32}$', pseudonym):
        await ui.display(
            event=message,
            text=(
                "✖ <b>INVALID IDENTITY</b>\n"
                "Псевдоним должен содержать от 2 до 32 символов (латиница, цифры, _ или -)."
            ),
        )
        return

    data = await state.get_data()
    user_service = UserService(session=session)
    
    # Регистрация временного профиля
    user = await user_service.register_seller(
        tg_user=message.from_user,
        language=data['language'],
    )
    user.pseudonym = pseudonym
    await session.commit() # Фиксируем псевдоним
    
    await _show_onboarding_faq(message, state, ui)

async def _show_onboarding_faq(event: Message | CallbackQuery, state: FSMContext, ui: MessageManager):
    """Экран базовой информации для селлера."""
    await state.set_state(RegistrationState.waiting_for_faq)
    
    from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
    text = (
        f"📖 <b>ОСНОВЫ РАБОТЫ // GDPX</b>\n"
        f"{DIVIDER}\n"
        f"Добро пожаловать в ряды агентов Синдиката. Перед началом ознакомьтесь с регламентом:\n\n"
        f"▫ <b>Загрузка:</b> Отправляйте только качественные сканы/фото eSIM.\n"
        f"▫ <b>Проверка:</b> Модерация занимает от 5 до 30 минут.\n"
        f"▫ <b>Выплаты:</b> Начисляются в USDT (BEP-20) сразу после зачета.\n"
        f"▫ <b>Ранги:</b> Чем больше активных сим, тем выше ваш % бонуса.\n\n"
        f"{DIVIDER_LIGHT}\n"
        f"<i>Нажмите «ДАЛЕЕ», чтобы изучить Кодекс Агента.</i>"
    )
    
    kb = PremiumBuilder().primary("⏭ ДАЛЕЕ", "reg:faq_next").as_markup()
    await ui.display(event=event, text=text, reply_markup=kb, photo=media.get("info.png"))

@router.callback_query(RegistrationState.waiting_for_faq, F.data == "reg:faq_next")
async def process_faq_next(callback: CallbackQuery, state: FSMContext, ui: MessageManager):
    """Переход к Кодексу."""
    await _show_onboarding_codex(callback, state, ui)
    await callback.answer()

async def _show_onboarding_codex(event: Message | CallbackQuery, state: FSMContext, ui: MessageManager):
    """Экран Кодекса с требованием подписки."""
    await state.set_state(RegistrationState.waiting_for_codex)
    
    from src.presentation.lexicon.ru import Lex
    from src.core.config import get_settings
    settings = get_settings()
    
    chat_url = settings.brand_chat_url or "https://t.me/gdpx_chat"
    
    text = (
        f"{Lex.Academy.CODEX_HEADER}\n\n"
        f"{Lex.Academy.CODEX_TEXT}\n\n"
        f"⚠️ <b>ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ:</b>\n"
        f"Вы должны состоять в официальном чате Академии для доступа к системе.\n\n"
        f"🔗 <b>ВСТУПИТЬ:</b> {chat_url}"
    )
    
    kb = (PremiumBuilder()
          .primary("🛡 ПРИНЯТЬ КОДЕКС", "reg:codex_accept")
          .row()
          .button("🔗 ПЕРЕЙТИ В ЧАТ", url=chat_url)
          .as_markup())
    
    await ui.display(event=event, text=text, reply_markup=kb, photo=media.get("info.png"))

@router.callback_query(RegistrationState.waiting_for_codex, F.data == "reg:codex_accept")
async def process_codex_accept(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager, bot: Bot):
    """Проверка подписки и финализация."""
    from src.core.config import get_settings
    settings = get_settings()
    chat_id = settings.brand_chat_id or -1003716766270 # Hardcoded as fallback per user request
    
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        if member.status in ["left", "kicked"]:
            return await callback.answer("✖ ОШИБКА: Вы должны вступить в чат Синдиката!", show_alert=True)
    except Exception as e:
        logger.error(f"Subscription check error: {e}")
        # Если чат не найден или бот не админ, можно пропустить или выдать ошибку
        # Но по ТЗ - обязательная проверка.
        return await callback.answer("⚠️ Не удалось проверить подписку. Попробуйте позже.", show_alert=True)

    # Успех
    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(callback.from_user.id)
    user.has_accepted_codex = True
    await session.commit()
    
    await state.clear()
    await callback.answer("✅ Добро пожаловать в элиту!", show_alert=True)
    await _show_main_dashboard(callback, user, session, ui)

from src.presentation.common.factory import SellerMenuCD


@router.callback_query(NavCD.filter(F.to == "menu"))
@router.callback_query(SellerMenuCD.filter(F.action == "main"))
async def back_to_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext, ui: MessageManager) -> None:
    """Возврат в меню через колбэк."""
    await state.clear()
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user:
        await _show_main_dashboard(callback, user, session, ui)
    await callback.answer()
