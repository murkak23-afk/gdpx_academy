from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.personal_epoch import get_personal_epoch
from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.keyboards.callbacks import CB_ADMIN_DASHBOARD_RESET
from src.keyboards.inline import admin_main_inline_keyboard
from src.services.admin_service import AdminService
from src.utils.ui_builder import GDPXRenderer


async def build_admin_main_inline_keyboard(session: AsyncSession, telegram_id: int) -> InlineKeyboardMarkup:
    show = await AdminService(session=session).can_access_payout_finance(telegram_id)
    kb = admin_main_inline_keyboard(show_payout_finance=show)
    # Добавляем кнопку сброса личных счётчиков
    reset_row = [InlineKeyboardButton(text="▫️ Обнулить показатели", callback_data=CB_ADMIN_DASHBOARD_RESET)]
    return InlineKeyboardMarkup(inline_keyboard=list(kb.inline_keyboard) + [reset_row])


async def send_admin_dashboard(message: Message, session: AsyncSession, user_id: int) -> None:
    """Отправляет дашборд главного меню админа новым сообщением."""

    pending = int((await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    )).scalar_one())
    in_review = int((await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW)
    )).scalar_one())

    # «Принято» и «Брак» считаем от личной точки сброса (если задана)
    epoch = get_personal_epoch(user_id)
    accepted_where = [Submission.status == SubmissionStatus.ACCEPTED]
    rejected_where = [Submission.status.in_([
        SubmissionStatus.REJECTED,
        SubmissionStatus.BLOCKED,
        SubmissionStatus.NOT_A_SCAN,
    ])]
    if epoch is not None:
        accepted_where.append(Submission.reviewed_at >= epoch)
        rejected_where.append(Submission.reviewed_at >= epoch)

    approved = int((await session.execute(
        select(func.count(Submission.id)).where(*accepted_where)
    )).scalar_one())
    rejected = int((await session.execute(
        select(func.count(Submission.id)).where(*rejected_where)
    )).scalar_one())

    actor = message.from_user.username if message.from_user else str(user_id)
    text = GDPXRenderer().render_admin_dashboard({
        "pending_count": pending,
        "in_review_count": in_review,
        "approved_count": approved,
        "rejected_count": rejected,
        "username": actor,
        "has_epoch": epoch is not None,
    })
    await message.answer(
        text,
        reply_markup=await build_admin_main_inline_keyboard(session, user_id),
        parse_mode="HTML",
    )

