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
from src.keyboards import language_choice_keyboard, seller_main_inline_keyboard
from src.services import BillingService, SubmissionService, UserService
from src.states.registration_state import RegistrationState
from src.utils.ui_builder import GDPXRenderer

router = Router(name="start-router")
logger = logging.getLogger(__name__)


async def _send_welcome_banner(
    message: Message,
    user: User,
    dashboard: dict[str, object],
    total_earned: object,
) -> None:
    username = user.username
    if not username:
        username = str(user.id)
    render_text = GDPXRenderer().render_dashboard(
        {
            "username": username,
            "pending_count": int(dashboard.get("pending", 0)),
            "in_review_count": 0,
            "approved_count": int(dashboard.get("accepted", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
            "total_payout_amount": total_earned,
            "payout_label": "Капитал:",
        },
    )
    # Hide legacy reply keyboard and send the inline profile hub in one message.
    await message.answer(
        render_text,
        reply_markup=seller_main_inline_keyboard(),
        parse_mode="HTML",
    )


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
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=existing_user.id)
        total_earned = await BillingService(session=session).get_user_total_paid_amount(existing_user.id)
        await _send_welcome_banner(
            message,
            existing_user,
            dashboard,
            total_earned,
        )
        return

    await state.set_state(RegistrationState.waiting_for_language)
    await message.answer(
        text="Добро пожаловать! Выбери язык интерфейса:",
        reply_markup=language_choice_keyboard(),
    )


@router.message(RegistrationState.waiting_for_language, F.text == "Русский")
async def on_language_selected(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Завершает регистрацию — интерфейс только на русском."""

    if message.from_user is None or message.text is None:
        return

    selected_language = UserLanguage.RU

    service = UserService(session=session)
    user = await service.register_seller(
        tg_user=message.from_user,
        language=selected_language,
    )

    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
    total_earned = await BillingService(session=session).get_user_total_paid_amount(user.id)
    await _send_welcome_banner(message, user, dashboard, total_earned)


@router.message(RegistrationState.waiting_for_language)
async def on_invalid_language(message: Message) -> None:
    """Просит выбрать язык только из доступных кнопок."""

    await message.answer(
        text="Пожалуйста, выбери язык кнопкой ниже.",
        reply_markup=language_choice_keyboard(),
    )
