from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import UserLanguage
from src.database.models.user import User
from src.keyboards import REPLY_BTN_BACK, language_choice_keyboard, seller_main_menu_keyboard
from src.services import SubmissionService, UserService
from src.states.registration_state import RegistrationState

router = Router(name="start-router")
logger = logging.getLogger(__name__)


def _welcome_profile_caption(user: User, lead: str) -> str:
    nickname = f"@{user.username}" if user.username else "без username"
    return (
        f"{lead}\n\n"
        "👤 Профиль\n"
        f"• Ник: {nickname}\n"
        f"• TG ID: {user.telegram_id}\n"
        f"• Роль: {user.role.value}\n"
        "• Статус: активен"
    )


async def _send_welcome_banner(
    message: Message,
    user: User,
    lead: str,
    dashboard: dict[str, object],
) -> None:
    caption = _welcome_profile_caption(user, lead)
    await message.answer(caption)


@router.message(CommandStart(ignore_mention=True))
async def on_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Обрабатывает /start и запускает регистрацию."""

    if message.from_user is None:
        return

    service = UserService(session=session)
    try:
        existing_user = await service.get_by_telegram_id(telegram_id=message.from_user.id)
    except SQLAlchemyError as exc:
        logger.exception("База данных недоступна при /start: %s", exc)
        await message.answer(
            "Сейчас не удаётся подключиться к базе данных. "
            "Проверь, что PostgreSQL запущен и переменные POSTGRES_* в .env совпадают с контейнером.\n"
            "Попробуй /start через минуту.",
        )
        return

    if existing_user is not None:
        await state.clear()
        menu = seller_main_menu_keyboard(language=existing_user.language, role=existing_user.role)
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=existing_user.id)
        await _send_welcome_banner(
            message,
            existing_user,
            "С возвращением! Выбери действие в меню.\nЕсли хочешь сменить язык, снова нажми /start.",
            dashboard,
        )
        await message.answer("Главное меню:", reply_markup=menu)
        return

    await state.set_state(RegistrationState.waiting_for_language)
    await message.answer(
        text="Добро пожаловать! Выбери язык интерфейса:",
        reply_markup=language_choice_keyboard(),
    )


@router.message(RegistrationState.waiting_for_language, F.text == REPLY_BTN_BACK)
async def on_registration_back(message: Message) -> None:
    """Не выходим из регистрации, но даём понятную подсказку."""

    await message.answer(
        "Чтобы продолжить, выбери язык кнопкой выше или позже команду /start.",
        reply_markup=language_choice_keyboard(),
    )


@router.message(RegistrationState.waiting_for_language, F.text.in_({"Русский", "English", "Polski"}))
async def on_language_selected(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Завершает регистрацию после выбора языка."""

    if message.from_user is None or message.text is None:
        return

    language_map: dict[str, UserLanguage] = {
        "Русский": UserLanguage.RU,
        "English": UserLanguage.EN,
        "Polski": UserLanguage.PL,
    }
    selected_language = language_map[message.text]

    service = UserService(session=session)
    user = await service.register_seller(
        tg_user=message.from_user,
        language=selected_language,
    )

    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
    await _send_welcome_banner(message, user, "Регистрация завершена. Добро пожаловать!", dashboard)
    await message.answer(
        "Теперь доступно главное меню.",
        reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
    )


@router.message(RegistrationState.waiting_for_language)
async def on_invalid_language(message: Message) -> None:
    """Просит выбрать язык только из доступных кнопок."""

    await message.answer(
        text="Пожалуйста, выбери язык кнопкой ниже.",
        reply_markup=language_choice_keyboard(),
    )
