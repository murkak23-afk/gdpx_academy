"""Матрица оценки (Grading Matrix) и Поиск симки для админов.

Обработчики:
  - 🔒 Взять в работу → lock + показ матрицы
  - ✅ ЗАЧЁТ → accept
  - ❌ Брак: Не скан → NOT_A_SCAN
  - ❌ Брак: Блок на холде → BLOCKED
  - ❌ Брак: Другое → FSM → произвольная причина
  - 🔍 Поиск симки → FSM → ввод 3-11 цифр → результаты
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.database.models.category import Category
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User
from src.handlers.moderation_flow import send_in_review_queue
from src.keyboards import grading_matrix_keyboard, moderation_item_keyboard, search_report_keyboard
from src.keyboards.callbacks import (
    CB_ADMIN_SEARCH_SIM,
    CB_GRADE_ACCEPT,
    CB_GRADE_BLOCKED,
    CB_GRADE_NOT_SCAN,
    CB_GRADE_OTHER,
    CB_GRADE_TAKE,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK, REPLY_BTN_BACK
from src.services import AdminAuditService, AdminService, SubmissionService, UserService
from src.states.admin_state import AdminGradeOtherState, AdminSearchSimState
from src.utils.submission_format import format_submission_chat_forward_title
from src.utils.submission_media import bot_send_submission
from src.utils.text_format import edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

router = Router(name="admin-grading-router")
_renderer = GDPXRenderer()


async def _return_to_in_work_if_possible(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Возвращает админа в SPA-раздел «В работе», если можно определить пользователя."""

    await state.clear()
    if message.from_user is None:
        return
    await send_in_review_queue(message, session, message.from_user.id)


# ═══════════════════════════════════════════════════════════════════
#  🔒 Взять в работу (lock + grading matrix)
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_GRADE_TAKE}:"))
async def on_grade_take(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """Блокирует симку за админом, показывает матрицу оценки."""

    if callback.from_user is None or callback.data is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    svc = SubmissionService(session=session)

    # Пробуем взять pending → in_review
    taken = await svc.take_to_work(submission_id=submission_id, admin_id=admin_user.id)
    if taken is None:
        # Может быть уже in_review — проверяем доступ
        existing = await svc.get_submission_in_work_for_admin(submission_id=submission_id, admin_id=admin_user.id)
        if existing is None:
            await callback.answer("⏳ Эту симку уже взял другой админ!", show_alert=True)
            return

    await callback.answer("✅ Симка взята в работу")

    if callback.message is not None:
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=callback.message.caption,
                    reply_markup=grading_matrix_keyboard(submission_id),
                )
            else:
                await callback.message.edit_reply_markup(
                    reply_markup=grading_matrix_keyboard(submission_id),
                )
        except TelegramAPIError:
            pass


# ═══════════════════════════════════════════════════════════════════
#  ✅ ЗАЧЁТ
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_GRADE_ACCEPT}:"))
async def on_grade_accept(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Принимает симку: начисляет сумму, архивирует."""

    if callback.from_user is None or callback.data is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    submission_obj = await session.get(Submission, submission_id)
    if submission_obj is None:
        await callback.answer("Симка не найдена", show_alert=True)
        return
    if submission_obj.status != SubmissionStatus.IN_REVIEW:
        await callback.answer("Симка уже обработана", show_alert=True)
        return

    svc = SubmissionService(session=session)

    settings = get_settings()
    await session.refresh(submission_obj, ["category"])
    if submission_obj.category is None and submission_obj.category_id is not None:
        submission_obj.category = await session.get(Category, submission_obj.category_id)

    archive_text = format_submission_chat_forward_title(submission_obj)
    if settings.moderation_chat_id == 0:
        await callback.answer("Не задан MODERATION_CHAT_ID в .env", show_alert=True)
        return

    archive_message = await bot_send_submission(
        bot, settings.moderation_chat_id, submission_obj, archive_text,
    )

    accepted = await svc.accept_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        archive_chat_id=settings.moderation_chat_id,
        archive_message_id=archive_message.message_id,
    )
    if accepted is None:
        await callback.answer("Симка уже обработана", show_alert=True)
        return

    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="grade_accept",
        target_type="submission",
        target_id=accepted.id,
        details=f"amount={accepted.accepted_amount}",
    )

    seller = await session.get(User, accepted.user_id)
    if seller is not None:
        try:
            await bot.send_message(
                chat_id=seller.telegram_id,
                text=f"✅ Симка #{accepted.id}: Зачёт. Начислено: {accepted.accepted_amount} USDT.",
            )
        except TelegramAPIError:
            pass

    await callback.answer("✅ Зачёт поставлен")

    if callback.message is not None:
        sent_at = accepted.reviewed_at.strftime("%d.%m.%Y %H:%M") if accepted.reviewed_at else "—"
        current_caption = (callback.message.caption or callback.message.text or "").strip()
        updated = f"✅ ЗАЧЁТ · {sent_at}\n\n{current_caption}"
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(caption=updated, reply_markup=None)
            else:
                await edit_message_text_safe(callback.message, updated, reply_markup=None)
        except TelegramAPIError:
            await callback.message.edit_reply_markup(reply_markup=None)

        await send_in_review_queue(callback.message, session, callback.from_user.id)


# ═══════════════════════════════════════════════════════════════════
#  ❌ Брак: Не скан
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_GRADE_NOT_SCAN}:"))
async def on_grade_not_scan(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    await _grade_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.NOT_A_SCAN,
        reason=RejectionReason.QUALITY,
        seller_text="❌ Симка отклонена: не скан / неподходящий формат.",
        audit_action="grade_not_scan",
    )


# ═══════════════════════════════════════════════════════════════════
#  ❌ Брак: Блок на холде
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_GRADE_BLOCKED}:"))
async def on_grade_blocked(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    await _grade_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.BLOCKED,
        reason=RejectionReason.RULES_VIOLATION,
        seller_text="❌ Симка заблокирована: блок на холде.",
        audit_action="grade_blocked",
    )


# ═══════════════════════════════════════════════════════════════════
#  ❌ Брак: Другое (FSM → ввод причины)
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith(f"{CB_GRADE_OTHER}:"))
async def on_grade_other_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Начинает FSM для ввода произвольной причины отказа."""

    if callback.from_user is None or callback.data is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    await state.set_state(AdminGradeOtherState.waiting_for_reason)
    await state.update_data(grade_other_submission_id=submission_id)
    await callback.answer()

    if callback.message is not None:
        try:
            await callback.message.answer(
                "✏️ Введите причину отказа текстом:",
            )
        except TelegramAPIError:
            pass


@router.message(AdminGradeOtherState.waiting_for_reason, F.text)
async def on_grade_other_reason(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    """Получает произвольную причину и отклоняет симку."""

    if message.from_user is None or message.text is None:
        return

    data = await state.get_data()
    submission_id = int(data.get("grade_other_submission_id", 0))

    if submission_id == 0:
        await message.answer("Ошибка: не найден ID симки. Попробуйте снова.")
        await _return_to_in_work_if_possible(message, state, session)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await message.answer("Пользователь не найден в БД.")
        await _return_to_in_work_if_possible(message, state, session)
        return

    svc = SubmissionService(session=session)

    custom_reason = message.text.strip()[:500]
    submission = await svc.final_reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        to_status=SubmissionStatus.REJECTED,
        reason=RejectionReason.OTHER,
        comment=custom_reason,
    )
    if submission is None:
        await message.answer("Симка уже обработана.")
        await _return_to_in_work_if_possible(message, state, session)
        return

    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="grade_other_reject",
        target_type="submission",
        target_id=submission.id,
        details=custom_reason,
    )

    seller = await session.get(User, submission.user_id)
    if seller is not None:
        try:
            await bot.send_message(
                chat_id=seller.telegram_id,
                text=f"❌ Симка #{submission.id} отклонена.\nПричина: {custom_reason}",
            )
        except TelegramAPIError:
            pass

    await message.answer(
        f"❌ Симка #{submission.id} отклонена. Причина: {escape(custom_reason)}",
        parse_mode="HTML",
    )
    await _return_to_in_work_if_possible(message, state, session)


# ═══════════════════════════════════════════════════════════════════
#  🔍 Поиск симки (по последним цифрам)
# ═══════════════════════════════════════════════════════════════════


@router.callback_query(F.data == CB_ADMIN_SEARCH_SIM)
async def on_search_sim_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запускает FSM поиска: ожидаем от 3 до 11 цифр."""

    if callback.from_user is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.set_state(AdminSearchSimState.waiting_for_digits)
    await callback.answer()

    if callback.message is not None:
        await callback.message.answer(
            "🔍 Введите последние 4 цифры или полный номер для поиска:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]]
            ),
        )


@router.message(AdminSearchSimState.waiting_for_digits, F.text)
async def on_search_sim_digits(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Выполняет поиск по суффиксу номера."""

    if message.from_user is None or message.text is None:
        return

    digits = "".join(ch for ch in message.text if ch.isdigit())
    if len(digits) < 3 or len(digits) > 11:
        _search_back_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]]
        )
        await message.answer(
            "❌ Введите от 3 до 11 цифр для поиска.",
            reply_markup=_search_back_kb,
        )
        return

    await state.clear()

    svc = SubmissionService(session=session)
    results = await svc.search_by_phone_suffix(digits)

    if not results:
        await message.answer(
            f"🔍 По запросу <code>…{escape(digits)}</code> ничего не найдено.",
            parse_mode="HTML",
        )
        return

    header = (
        f"🔍 Найдено: <b>{len(results)}</b> симок по суффиксу <code>…{escape(digits)}</code>\n\n"
        "Выберите карточку ниже или перейдите в другой раздел меню."
    )
    await message.answer(
        header,
        parse_mode="HTML",
    )

    for sub in results:
        is_dup = await svc.has_phone_duplicate(submission_id=sub.id, phone=sub.description_text)
        card = _renderer.render_moderation_card(sub, is_duplicate=is_dup)

        if sub.status == SubmissionStatus.PENDING:
            markup = moderation_item_keyboard(sub.id)
        else:
            markup = search_report_keyboard(sub.id, seller_user_id=sub.user_id)

        await message.answer(card, parse_mode="HTML", reply_markup=markup)


# ═══════════════════════════════════════════════════════════════════
#  Общий обработчик отклонения для grade_not_scan / grade_blocked
# ═══════════════════════════════════════════════════════════════════


async def _grade_reject(
    *,
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    to_status: SubmissionStatus,
    reason: RejectionReason,
    seller_text: str,
    audit_action: str,
) -> None:
    """Общий хелпер отклонения из матрицы оценки."""

    if callback.from_user is None or callback.data is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    svc = SubmissionService(session=session)

    submission = await svc.final_reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        to_status=to_status,
        reason=reason,
        comment=seller_text,
    )
    if submission is None:
        await callback.answer("Симка уже обработана", show_alert=True)
        return

    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action=audit_action,
        target_type="submission",
        target_id=submission.id,
        details=seller_text,
    )

    seller = await session.get(User, submission.user_id)
    if seller is not None:
        try:
            await bot.send_message(chat_id=seller.telegram_id, text=f"Симка #{submission.id}: {seller_text}")
        except TelegramAPIError:
            pass

    await callback.answer("❌ Отклонено")

    if callback.message is not None:
        rejected_at = (
            submission.reviewed_at.strftime("%d.%m.%Y %H:%M")
            if submission.reviewed_at
            else datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
        )
        status_label = {
            SubmissionStatus.NOT_A_SCAN: "❌ БРАК: НЕ СКАН",
            SubmissionStatus.BLOCKED: "❌ БРАК: БЛОК НА ХОЛДЕ",
            SubmissionStatus.REJECTED: "❌ БРАК",
        }.get(to_status, "❌ ОТКЛОНЕНО")

        current_caption = (callback.message.caption or callback.message.text or "").strip()
        updated = f"{status_label} · {rejected_at}\n\n{current_caption}"
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(caption=updated, reply_markup=None)
            else:
                await edit_message_text_safe(callback.message, updated, reply_markup=None)
        except TelegramAPIError:
            await callback.message.edit_reply_markup(reply_markup=None)

        await send_in_review_queue(callback.message, session, callback.from_user.id)
