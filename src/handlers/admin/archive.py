from __future__ import annotations

import asyncio
import re
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.handlers.admin_menu import PHONE_QUERY_PATTERN, _render_admin_moderation_card
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.keyboards import pagination_keyboard, search_report_keyboard
from src.keyboards.callbacks import (
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_SEARCH_PAGE,
    CB_ADMIN_UNRESTRICT,
)
from src.services import AdminAuditService, AdminService, SubmissionService, UserService
from src.utils.submission_format import submission_status_emoji_line
from src.utils.submission_media import message_answer_submission
from src.utils.text_format import non_empty_plain

router = Router(name="admin-archive-router")

PAGE_SIZE = 5


async def _delete_message_later(bot, chat_id: int, message_id: int, delay_sec: int = 20) -> None:
    await asyncio.sleep(delay_sec)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass


@router.message(Command("s"))
async def on_search_submission(message: Message, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    raw_query = message.text.replace("/s", "", 1).strip()
    if not raw_query:
        await message.answer("Формат: /s 1234 или /s +79999999999")
        return

    digits = re.sub(r"\D", "", raw_query)
    if not PHONE_QUERY_PATTERN.fullmatch(raw_query) and len(digits) < 3:
        await message.answer("Укажи минимум 3 последние цифры или полный номер.")
        return

    rows, total = await SubmissionService(session=session).search_by_phone_paginated(
        query=raw_query,
        page=0,
        page_size=PAGE_SIZE,
    )
    if not rows:
        await message.answer("Ничего не найдено по этому запросу.")
        return

    for submission, _seller in rows:
        cap = await _render_admin_moderation_card(session=session, submission=submission)
        await message_answer_submission(
            message,
            submission,
            caption=cap,
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            parse_mode="HTML",
        )
    await message.answer(
        "Навигация поиска:",
        reply_markup=pagination_keyboard(
            CB_ADMIN_SEARCH_PAGE,
            page=0,
            total=total,
            page_size=PAGE_SIZE,
            query=raw_query,
        ),
    )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_SEARCH_PAGE}:"))
async def on_search_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    _, _, page_raw, query = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    rows, total = await SubmissionService(session=session).search_by_phone_paginated(
        query=query,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        for submission, _seller in rows:
            cap = await _render_admin_moderation_card(session=session, submission=submission)
            await message_answer_submission(
                callback.message,
                submission,
                caption=cap,
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
                parse_mode="HTML",
            )
        await callback.message.answer(
            "Навигация поиска:",
            reply_markup=pagination_keyboard(
                CB_ADMIN_SEARCH_PAGE,
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=query,
            ),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_ADMIN_RESTRICT}:"))
async def on_restrict_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None or not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    target = await UserService(session=session).set_restricted(user_id=user_id, value=True)
    if target is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin.id,
        action="set_restricted",
        target_type="user",
        target_id=user_id,
        details="manual from admin report",
    )
    await callback.answer("Ограничение включено")


@router.callback_query(F.data.startswith(f"{CB_ADMIN_UNRESTRICT}:"))
async def on_unrestrict_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None or not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    target = await UserService(session=session).set_restricted(user_id=user_id, value=False)
    if target is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin.id,
        action="unset_restricted",
        target_type="user",
        target_id=user_id,
        details="manual from admin report",
    )
    await callback.answer("Ограничение снято")


@router.callback_query(F.data.startswith(f"{CB_ADMIN_REPORT_SUBMISSION}:"))
async def on_submission_report(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    submission = await session.get(Submission, submission_id)
    if submission is None:
        await callback.answer("Товар не найден", show_alert=True)
        return

    seller = await session.get(User, submission.user_id)
    seller_nickname = f"@{seller.username}" if seller is not None and seller.username else f"@{submission.user_id}"
    category_title = submission.category.title if submission.category is not None else "Без категории"

    actions_stmt = (
        select(ReviewAction).where(ReviewAction.submission_id == submission.id).order_by(ReviewAction.created_at.asc())
    )
    actions = list((await session.execute(actions_stmt)).scalars().all())
    history_lines = [
        f"- {action.created_at}: "
        f"{action.from_status.value if action.from_status else 'none'} -> {action.to_status.value}"
        for action in actions
    ]
    history_text = "\n".join(history_lines) if history_lines else "- без изменений статуса"

    number_line = non_empty_plain((submission.description_text or "").strip(), placeholder="—")
    report_lines = [
        "❖ <b>GDPX // ACADEMY</b> ─ Спецификация\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>АРХИВНЫЙ ОТЧЕТ #{submission.id}</b>",
        "",
        f"◾️ <b>Продавец:</b> {seller_nickname}\n"
        f"◾️ <b>Категория:</b> {category_title}\n"
        f"◾️ <b>SIM:</b> <code>{number_line}</code> — {category_title}\n"
        f"◾️ <b>Статус:</b> {submission_status_emoji_line(submission.status)}",
        "",
        "<b>ВРЕМЕННЫЕ МЕТКИ:</b>",
        f"▫️ Создано: <code>{submission.created_at}</code>\n"
        f"▫️ Взято в работу: <code>{submission.assigned_at}</code>\n"
        f"▫️ Проверено: <code>{submission.reviewed_at}</code>\n"
        "",
        f"◾️ <b>Начислено:</b> <code>{submission.accepted_amount}</code>\n\n"
        "История статусов:\n"
        f"{history_text}",
    ]

    if getattr(submission, "is_duplicate", False):
        report_lines.insert(2, "✕ <b>ВНИМАНИЕ: ДУБЛИКАТ В РЕЕСТРЕ</b>")
        report_lines.insert(3, "")

    report_text = "\n".join(report_lines)

    await callback.answer("Спецификация сформирована")

    sent = None
    if callback.message:
        sent = await callback.message.answer(
            report_text + "\n\n<i>Системное сообщение. Самоуничтожение через 20 сек.</i>",
            parse_mode="HTML"
        )
    if sent is not None and sent.chat is not None:
        asyncio.create_task(
            _delete_message_later(
                callback.bot,
                chat_id=sent.chat.id,
                message_id=sent.message_id,
                delay_sec=20,
            )
        )
