from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.keyboards.inline import admin_main_inline_keyboard
from src.services.admin_service import AdminService
from src.utils.ui_builder import GDPXRenderer


async def build_admin_main_inline_keyboard(session: AsyncSession, telegram_id: int) -> InlineKeyboardMarkup:
    show = await AdminService(session=session).can_access_payout_finance(telegram_id)
    return admin_main_inline_keyboard(show_payout_finance=show)


async def send_admin_dashboard(message: Message, session: AsyncSession, user_id: int) -> None:
    """Отправляет дашборд главного меню админа новым сообщением."""

    pending = int((await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    )).scalar_one())
    in_review = int((await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW)
    )).scalar_one())
    approved = int((await session.execute(
        select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.ACCEPTED)
    )).scalar_one())
    rejected = int((await session.execute(
        select(func.count(Submission.id)).where(
            Submission.status.in_([
                SubmissionStatus.REJECTED,
                SubmissionStatus.BLOCKED,
                SubmissionStatus.NOT_A_SCAN,
            ])
        )
    )).scalar_one())

    actor = message.from_user.username if message.from_user else str(user_id)
    text = GDPXRenderer().render_dashboard({
        "pending_count": pending,
        "in_review_count": in_review,
        "approved_count": approved,
        "rejected_count": rejected,
        "username": actor,
    })
    await message.answer(
        text,
        reply_markup=await build_admin_main_inline_keyboard(session, user_id),
        parse_mode="HTML",
    )
