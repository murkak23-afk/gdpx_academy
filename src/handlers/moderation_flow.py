from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from html import escape
from io import StringIO

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.database.models.category import Category
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User
from src.keyboards import (
    forward_target_reply_keyboard,
    hold_condition_keyboard,
    match_admin_menu_canonical,
    moderation_item_keyboard,
    moderation_reject_template_keyboard,
    moderation_review_keyboard,
    moderation_seller_group_keyboard,
    pagination_keyboard,
)
from src.keyboards.admin_hints import HINT_IN_REVIEW, HINT_QUEUE
from src.keyboards.callbacks import (
    CB_MOD_ACCEPT,
    CB_MOD_BATCH_ACTION,
    CB_MOD_BATCH_CANCEL,
    CB_MOD_BATCH_CONFIRM,
    CB_MOD_DEBIT,
    CB_MOD_FORWARD_CANCEL,
    CB_MOD_FORWARD_CONFIRM,
    CB_MOD_FORWARD_CONFIRM_CANCEL,
    CB_MOD_HOLD_SELECT,
    CB_MOD_HOLD_SKIP,
    CB_MOD_IN_REVIEW_PAGE,
    CB_MOD_PICK_CANCEL,
    CB_MOD_QUEUE_PAGE,
    CB_MOD_REJECT,
    CB_MOD_REJTPL,
    CB_MOD_REJTPL_BACK,
    CB_MOD_TAKE,
    CB_MOD_TAKE_PICK,
)
from src.services import (
    AdminAuditService,
    AdminChatForwardStatsService,
    AdminService,
    SubmissionService,
    UserService,
)
from src.states.moderation_state import AdminBatchPickState, AdminModerationForwardState
from src.utils.admin_keyboard import send_admin_dashboard
from src.utils.clean_screen import send_clean_text_screen
from src.utils.forward_target import target_chat_id_from_forward_pick
from src.utils.submission_format import (
    duplicate_warning_html,
    format_phone_category_html,
    format_submission_chat_forward_title,
    submission_status_emoji_line,
)
from src.utils.submission_media import bot_send_submission, message_answer_submission
from src.utils.text_format import edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

router = Router(name="moderation-router")
PAGE_SIZE = 5
_renderer = GDPXRenderer()
logger = logging.getLogger(__name__)


async def _notify_sellers_in_review(bot: Bot, session: AsyncSession, submissions: list[Submission]) -> None:
    for s in submissions:
        u = await session.get(User, s.user_id)
        if u is None:
            continue
        num = (s.description_text or "").strip() or "—"
        try:
            await bot.send_message(
                chat_id=u.telegram_id,
                text=f"⚖️ Ваш актив  <code>{escape(num)}</code>  передан в управление модератору. Ожидайте решения.",
                parse_mode="HTML",
            )
        except TelegramAPIError:
            pass


async def _return_after_final_review(
    *,
    message: Message,
    session: AsyncSession,
    telegram_id: int,
    admin_id: int,
) -> None:
    remaining = await SubmissionService(session=session).get_admin_active_submissions(admin_id=admin_id)
    if remaining:
        await message.answer(
            f"Проверка завершена. В разделе «В работе» осталось карточек: {len(remaining)}.",
        )
        await send_in_review_queue(message, session, telegram_id)
        return

    await message.answer(
        "Проверка завершена. В разделе «В работе» больше нет карточек. Возврат в главное меню.",
    )
    await send_admin_dashboard(message, session, telegram_id)


def _reply_is_queue(t: str | None) -> bool:
    return match_admin_menu_canonical(t) == "Очередь"


def _reply_is_in_review(t: str | None) -> bool:
    return match_admin_menu_canonical(t) in {"В работе", "🏃 В работе"}


def _encode_queue_filters(seller_id: int | None, category_id: int | None, date_from: datetime | None) -> str:
    """Кодирует фильтры очереди в query-поле callback_data без двоеточий."""

    def _v(v: int | None) -> str:
        return str(v) if v is not None else ""

    def _d(v: datetime | None) -> str:
        if v is None:
            return ""
        return v.date().isoformat()  # YYYY-MM-DD (без ':')

    # Используем '|' и '=' чтобы не ломать split(":", 3) в обработчике.
    return f"s={_v(seller_id)}|c={_v(category_id)}|d={_d(date_from)}"


def _decode_queue_filters(raw: str | None) -> tuple[int | None, int | None, datetime | None]:
    if not raw:
        return None, None, None

    seller_id: int | None = None
    category_id: int | None = None
    date_from: datetime | None = None

    # Ожидаем формат: s=...|c=...|d=...
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    for part in parts:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        v = v.strip()
        if k == "s" and v.isdigit():
            seller_id = int(v)
        elif k == "c" and v.isdigit():
            category_id = int(v)
        elif k == "d" and v:
            try:
                # Берём только дату (UTC-наблюдение), чтобы не ловить время/таймзону.
                date_from = datetime.fromisoformat(v)
            except ValueError:
                continue

    return seller_id, category_id, date_from


@router.callback_query(F.data.startswith(f"{CB_MOD_REJTPL_BACK}:"))
async def on_reject_template_back(callback: CallbackQuery, session: AsyncSession) -> None:
    """Возврат с выбора причины отклонения к кнопкам симки."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[2])
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=moderation_item_keyboard(submission_id=submission_id))


def _format_pending_list_for_pick(pending: list[Submission]) -> str:
    """Список ID и короткого описания для выбора части пачки."""

    lines: list[str] = []
    for s in pending:
        desc = (s.description_text or "").strip()
        lines.append(f"#{s.id} — {desc[:100]}")
    text = "\n".join(lines)
    if len(text) > 3500:
        return text[:3490] + "\n…"
    return text


def _parse_submission_id_selection(text: str, pending_by_id: dict[int, Submission]) -> list[int]:
    """Парсит номера submission: перечисление и диапазоны «3-12» (включительно), только из pending."""

    ids: list[int] = []
    seen: set[int] = set()
    for raw in re.split(r"[\s,;]+", text.strip()):
        if not raw:
            continue
        if re.match(r"^\d+\s*-\s*\d+$", raw):
            a, b = re.split(r"\s*-\s*", raw, maxsplit=1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            for i in range(lo, hi + 1):
                if i in pending_by_id and i not in seen:
                    seen.add(i)
                    ids.append(i)
            continue
        if raw.isdigit():
            n = int(raw)
            if n in pending_by_id and n not in seen:
                seen.add(n)
                ids.append(n)
    pending_sorted = sorted(pending_by_id.keys())
    return sorted(ids, key=lambda x: pending_sorted.index(x))


def _parse_filters(text: str | None) -> tuple[int | None, int | None, datetime | None]:
    if not text:
        return None, None, None
    seller_id = None
    category_id = None
    date_from = None
    for token in text.split():
        if token.startswith("seller=") and token.split("=", 1)[1].isdigit():
            seller_id = int(token.split("=", 1)[1])
        if token.startswith("category=") and token.split("=", 1)[1].isdigit():
            category_id = int(token.split("=", 1)[1])
        if token.startswith("date="):
            try:
                date_from = datetime.fromisoformat(token.split("=", 1)[1])
            except ValueError:
                continue
    return seller_id, category_id, date_from


async def _render_moderation_card_caption(
    submission: Submission,
    *,
    session: AsyncSession,
    hint_block: str = "",
) -> str:
    is_duplicate = await SubmissionService(session=session).has_phone_duplicate(
        submission_id=submission.id,
        phone=submission.description_text,
    )
    card = _renderer.render_moderation_card(submission, is_duplicate=is_duplicate)
    
    # Добавляем инфо о холде если она есть
    hold_block = ""
    if submission.hold_assigned:
        hold_label = (
            "Безхолд"
            if submission.hold_assigned == "no_hold"
            else f"{submission.hold_assigned[:-1]}м"
        )
        hold_block = f"\n⏱ <b>Холд:</b> {hold_label}"
    
    full_card = f"{card}{hold_block}"
    if hint_block:
        return f"{hint_block}\n\n{full_card}"
    return full_card


async def _show_queue_for_admin(
    *,
    target_message: Message,
    session: AsyncSession,
    seller_id: int | None = None,
    category_id: int | None = None,
    date_from: datetime | None = None,
) -> None:
    """Показывает первую страницу очереди для админа в текущем чате."""

    filters_query = _encode_queue_filters(seller_id=seller_id, category_id=category_id, date_from=date_from)
    groups, total = await SubmissionService(session=session).list_pending_groups_by_user_paginated(
        page=0,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    if not groups:
        if target_message.from_user is None:
            await target_message.answer("Очередь пустая.")
            return
        await target_message.answer("Очередь пустая.")
        return

    first_card = True
    for seller_user_id, items_count in groups:
        sample_items = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
        if not sample_items:
            continue
        sample = sample_items[0]
        cap = await _render_moderation_card_caption(
            sample,
            session=session,
            hint_block=HINT_QUEUE if first_card else "",
        )
        if first_card:
            first_card = False
        await message_answer_submission(
            target_message,
            sample,
            caption=cap,
            reply_markup=moderation_seller_group_keyboard(user_id=seller_user_id),
            parse_mode="HTML",
        )
    if total > PAGE_SIZE:
        await target_message.answer(
            "Навигация по очереди:",
            reply_markup=pagination_keyboard(
                CB_MOD_QUEUE_PAGE,
                page=0,
                total=total,
                page_size=PAGE_SIZE,
                query=filters_query,
            ),
        )


@router.message(Command("moderation"))
async def on_moderation_queue(
    message: Message, session: AsyncSession, *, _caller_id: int | None = None
) -> None:
    """Показывает очередь pending, сгруппированную по продавцам."""

    tid = _caller_id or (message.from_user.id if message.from_user else None)
    if tid is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(tid):
        await message.answer("Недостаточно прав.")
        return

    seller_id, category_id, date_from = _parse_filters(message.text)
    await _show_queue_for_admin(
        target_message=message,
        session=session,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )


@router.callback_query(F.data.startswith(f"{CB_MOD_QUEUE_PAGE}:"))
async def on_queue_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, page_raw, query_raw = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    seller_id, category_id, date_from = _decode_queue_filters(query_raw)
    groups, total = await SubmissionService(session=session).list_pending_groups_by_user_paginated(
        page=page,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    if callback.message is not None:
        # Обновляем существующее сообщение пагинации
        await edit_message_text_safe(
            callback.message,
            "Навигация по очереди:",
            reply_markup=pagination_keyboard(
                CB_MOD_QUEUE_PAGE,
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=_encode_queue_filters(seller_id=seller_id, category_id=category_id, date_from=date_from),
            ),
        )
        first_card = True
        for seller_user_id, items_count in groups:
            sample_items = await SubmissionService(session=session).list_pending_submissions_by_user(
                user_id=seller_user_id
            )
            if not sample_items:
                continue
            sample = sample_items[0]
            cap = await _render_moderation_card_caption(
                sample,
                session=session,
                hint_block=HINT_QUEUE if page == 0 and first_card else "",
            )
            if page == 0 and first_card:
                first_card = False
            await message_answer_submission(
                callback.message,
                sample,
                caption=cap,
                reply_markup=moderation_seller_group_keyboard(user_id=seller_user_id),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_MOD_TAKE_PICK}:"))
async def on_take_pick_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Старт выбора части симок по ID перед пересылкой."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    seller_user_id = int(callback.data.split(":")[2])
    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    if not pending:
        await callback.answer("У продавца нет pending-симок", show_alert=True)
        return

    await state.set_state(AdminBatchPickState.waiting_for_submission_ids)
    await state.update_data(seller_user_id=seller_user_id)
    await callback.answer()
    list_text = _format_pending_list_for_pick(pending)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_MOD_PICK_CANCEL)]]
    )
    await callback.message.answer(  # type: ignore[union-attr]
        "Укажи, какие товары переслать в чат или ЛС (по **индивидуальному ID** из списка).\n\n"
        "Примеры:\n"
        "• `101, 102, 105` — три конкретных номера\n"
        "• `3-12` — все pending с ID от 3 до 12 включительно "
        "(если в очереди есть 3, 6, 9 — уйдут все, что попали в диапазон)\n"
        "• можно комбинировать: `100-105, 200`\n\n"
        "После выбора бот попросит цель (группа / канал / ЛС). Остальные симки продавца останутся в очереди.\n\n"
        f"Список:\n{list_text}",
        parse_mode="Markdown",
        reply_markup=cancel_kb,
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == CB_MOD_PICK_CANCEL)
async def on_pick_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Отмена режима выбора ID."""

    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None and callback.from_user is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Выбор отменён.")
        await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.message(AdminBatchPickState.waiting_for_submission_ids, F.text)
async def on_batch_pick_ids_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Принимает список ID и предлагает выбрать чат для частичной пересылки."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    data = await state.get_data()
    seller_user_id = int(data["seller_user_id"])
    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    pending_by_id = {s.id: s for s in pending}

    valid_ids = _parse_submission_id_selection(message.text, pending_by_id)

    if not valid_ids:
        await message.answer(
            "Ни один из указанных ID не найден в pending у этого продавца. "
            "Проверь номера или диапазон и отправь снова.",
        )
        return

    await state.update_data(picked_submission_ids=valid_ids)
    await state.set_state(AdminBatchPickState.waiting_for_action)
    actions_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Взять в работу", callback_data=f"{CB_MOD_BATCH_ACTION}:take_work")],
            [InlineKeyboardButton(text="Переслать в чат / ЛС", callback_data=f"{CB_MOD_BATCH_ACTION}:forward")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_MOD_PICK_CANCEL)],
        ]
    )
    await message.answer(
        f"Выбрано карточек: {len(valid_ids)}.\n\nВыбери действие для этой пачки:",
        reply_markup=actions_kb,
    )


@router.callback_query(F.data.startswith(f"{CB_MOD_BATCH_ACTION}:"))
async def on_batch_action_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Этап 2 inbox: выбор массового действия над выбранными симками."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    action = callback.data.split(":")[2]
    data = await state.get_data()
    seller_user_id = int(data.get("seller_user_id", 0))
    picked_ids = [int(x) for x in data.get("picked_submission_ids", [])]
    if seller_user_id <= 0 or not picked_ids:
        await state.clear()
        await callback.answer("Выбранная пачка устарела, открой «Очередь» заново.", show_alert=True)
        return

    if action == "forward":
        await state.set_state(AdminModerationForwardState.waiting_for_target)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                "Выбери группу, канал или пользователя для ЛС:",
                reply_markup=forward_target_reply_keyboard(),
            )
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    if action != "take_work":
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{CB_MOD_BATCH_CONFIRM}:take_work")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_MOD_BATCH_CANCEL)],
        ]
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            f"Подтвердить перевод в «В работе» для {len(picked_ids)} карточек?",
            reply_markup=confirm_kb,
        )
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(f"{CB_MOD_BATCH_CONFIRM}:"))
async def on_batch_action_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Подтверждение массового перевода пачки в работу."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    action = callback.data.split(":")[2]
    if action != "take_work":
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    data = await state.get_data()
    seller_user_id = int(data.get("seller_user_id", 0))
    picked_ids = [int(x) for x in data.get("picked_submission_ids", [])]
    if seller_user_id <= 0 or not picked_ids:
        await state.clear()
        await callback.answer("Выбранная пачка устарела, открой «Очередь» заново.", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await state.clear()
        await callback.answer("Админ не найден в БД", show_alert=True)
        return
    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    id_set = set(picked_ids)
    submissions = [s for s in pending if s.id in id_set]
    marked = await SubmissionService(session=session).mark_submissions_in_review(
        submissions=submissions,
        admin_id=admin_user.id,
    )
    if marked:
        await _notify_sellers_in_review(bot, session, marked)
    await state.clear()
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="take_batch_to_work",
        target_type="user",
        target_id=seller_user_id,
        details=f"submission_ids={picked_ids}, marked={len(marked)}",
    )
    await callback.answer("Готово")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"Взято в работу: {len(marked)}. Остальные симки остались в «Очереди».",
        )
        await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.callback_query(F.data == CB_MOD_BATCH_CANCEL)
async def on_batch_action_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отмена подтверждения массового действия."""

    if callback.from_user is None:
        return
    await callback.answer("Отменено")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Действие отменено.")
        await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.message(
    AdminModerationForwardState.waiting_for_target,
    or_f(F.content_type == ContentType.CHAT_SHARED, F.content_type == ContentType.USER_SHARED),
)
async def on_moderation_forward_target_shared(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Пересылает пачку или выбранные симки в выбранный чат или ЛС."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    target_chat_id = target_chat_id_from_forward_pick(message)
    if target_chat_id is None:
        await message.answer("Используй кнопки выбора группы, канала или пользователя.")
        return
    if target_chat_id == bot.id:
        await message.answer("Нельзя выбирать самого бота как цель пересылки. Выбери группу, канал или пользователя.")
        return

    data = await state.get_data()
    picked_ids_for_audit = list(data.get("picked_submission_ids", []))
    if not picked_ids_for_audit:
        await state.clear()
        await message.answer("Не выбраны симки. Начни с очереди.")
        return

    await state.update_data(target_chat_id=target_chat_id)
    await state.set_state(AdminModerationForwardState.waiting_for_confirm)
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить пересылку", callback_data=CB_MOD_FORWARD_CONFIRM)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_MOD_FORWARD_CONFIRM_CANCEL)],
        ]
    )
    await message.answer(
        f"Подтвердить пересылку {len(picked_ids_for_audit)} карточек в target `{target_chat_id}`?",
        parse_mode="Markdown",
        reply_markup=confirm_kb,
    )


@router.callback_query(F.data == CB_MOD_FORWARD_CONFIRM)
async def on_moderation_forward_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await state.clear()
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    data = await state.get_data()
    seller_user_id = int(data.get("seller_user_id", 0))
    picked_ids_for_audit = [int(x) for x in data.get("picked_submission_ids", [])]
    target_chat_id = int(data.get("target_chat_id", 0))
    if seller_user_id <= 0 or not picked_ids_for_audit or target_chat_id == 0:
        await state.clear()
        await callback.answer("Данные пересылки устарели, начни заново.", show_alert=True)
        return

    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    id_set = set(picked_ids_for_audit)
    submissions = [s for s in pending if s.id in id_set]
    if not submissions:
        await state.clear()
        await callback.answer("Подходящих карточек в pending больше нет.", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await state.clear()
        await callback.answer("Админ не найден в БД", show_alert=True)
        return

    sent_count = 0
    failed_ids: list[int] = []
    failed_errors: list[str] = []
    for item in submissions:
        try:
            await bot_send_submission(
                bot,
                target_chat_id,
                item,
                caption=format_submission_chat_forward_title(item),
            )
            sent_count += 1
        except TelegramAPIError as exc:
            failed_ids.append(item.id)
            err = str(exc)
            if err:
                failed_errors.append(err)

    if sent_count > 0:
        await AdminChatForwardStatsService(session=session).add_forwards_for_telegram_chat(
            target_chat_id,
            sent_count,
        )
    successfully_sent = [s for s in submissions if s.id not in set(failed_ids)]
    marked = await SubmissionService(session=session).mark_submissions_in_review(
        submissions=successfully_sent,
        admin_id=admin_user.id,
    )
    if marked:
        await _notify_sellers_in_review(bot, session, marked)

    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="take_partial_batch",
        target_type="user",
        target_id=seller_user_id,
        details=(
            f"chat_id={target_chat_id}, submission_ids={picked_ids_for_audit}, "
            f"sent={sent_count}, failed_ids={failed_ids}, errors={failed_errors[:3]}, marked={len(marked)}"
        ),
    )

    if sent_count == 0:
        await callback.answer("Не удалось отправить карточки", show_alert=True)
    else:
        await callback.answer(f"Пересылка выполнена: {sent_count}")

    # Сохраняем переслано список и показываем первую карточку для выбора холда
    if successfully_sent:
        await state.update_data(
            forwarded_submitted_ids=[s.id for s in successfully_sent],
            current_forward_index=0,
            forwarded_submissions={s.id: s for s in successfully_sent},
        )
        await state.set_state(AdminModerationForwardState.waiting_for_hold_selection)

        # Показываем первую карточку
        first_submission = successfully_sent[0]
        cap = await _render_moderation_card_caption(first_submission, session=session)
        hint = "⏱ Выбери условие холда для этого товара"
        full_caption = f"{hint}\n\n{cap}"
        
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
            await message_answer_submission(
                callback.message,
                first_submission,
                caption=full_caption,
                reply_markup=hold_condition_keyboard(first_submission.id),
                parse_mode="HTML",
            )
    else:
        await state.clear()
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
            sample_error = failed_errors[0] if failed_errors else "неизвестная ошибка"
            await callback.message.answer(
                (
                    "❌ Не удалось отправить ни одной карточки. "
                    "Проверь, что бот добавлен в целевой чат и имеет право отправлять сообщения.\n"
                    f"Ошибок пересылки: {len(failed_ids)}.\n"
                    f"Причина Telegram: {sample_error}"
                    if sent_count == 0
                    else f"Переслано: {sent_count}. Ошибок пересылки: {len(failed_ids)}. "
                    f"Остальные pending остались в очереди."
                )
            )
            await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.callback_query(F.data == CB_MOD_FORWARD_CONFIRM_CANCEL)
async def on_moderation_forward_confirm_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user is None:
        return
    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None and callback.from_user is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Пересылка отменена.")
        await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.callback_query(F.data.startswith(f"{CB_MOD_HOLD_SELECT}:"))
async def on_moderation_hold_select(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Обработчик выбора условия холда после пересылки товара."""
    if callback.from_user is None:
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("❌ Ошибка обработки", show_alert=True)
            return

        submission_id = int(parts[2])
        hold_value = parts[3]  # no_hold, 15m, 30m

        # Получаем текущее состояние
        data = await state.get_data()
        forwarded_ids = data.get("forwarded_submitted_ids", [])
        current_index = data.get("current_forward_index", 0)

        admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        if admin_user is None:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        # Обновляем холд у товара
        submission = await SubmissionService(session=session).get_by_id(submission_id)
        if submission is None:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        # Сохраняем холд
        submission.hold_assigned = hold_value
        session.add(submission)
        await session.flush()

        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="assign_hold",
            target_type="submission",
            target_id=submission_id,
            details=f"hold_condition={hold_value}",
        )

        hold_label = (
            "Безхолд"
            if hold_value == "no_hold"
            else f"{hold_value[:-1]}м"
        )

        # Очищаем кнопки текущего сообщения
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)

        # Переходим к следующему товару или в меню
        next_index = current_index + 1
        if next_index < len(forwarded_ids):
            # Есть еще товары - показываем следующий
            next_submission_id = forwarded_ids[next_index]
            next_submission = await SubmissionService(session=session).get_by_id(next_submission_id)

            if next_submission is not None:
                await state.update_data(current_forward_index=next_index)

                cap = await _render_moderation_card_caption(next_submission, session=session)
                hint = "⏱ Выбери условие холда для этого товара"
                full_caption = f"{hint}\n\n{cap}"

                # Отправляем следующий товар
                if callback.message is not None:
                    await message_answer_submission(
                        callback.message,
                        next_submission,
                        caption=full_caption,
                        reply_markup=hold_condition_keyboard(next_submission_id),
                        parse_mode="HTML",
                    )
        else:
            # Все товары обработаны - возврат в меню
            if callback.message is not None:
                await callback.message.answer(
                    f"✅ Все товары обработаны! Последний холд: {hold_label}"
                )
                await send_admin_dashboard(callback.message, session, callback.from_user.id)

            await state.clear()

        await callback.answer(f"✅ Холд: {hold_label}")

    except Exception as e:
        logger.error(f"Error in on_moderation_hold_select: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
        if callback.message is not None and callback.from_user is not None:
            await send_admin_dashboard(callback.message, session, callback.from_user.id)
        await state.clear()


@router.callback_query(F.data.startswith(f"{CB_MOD_HOLD_SKIP}:"))
async def on_moderation_hold_skip(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обработчик пропуска выбора холда для товара."""
    if callback.from_user is None:
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("❌ Ошибка обработки", show_alert=True)
            return

        submission_id = int(parts[2])

        # Получаем текущее состояние
        data = await state.get_data()
        forwarded_ids = data.get("forwarded_submitted_ids", [])
        current_index = data.get("current_forward_index", 0)

        admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
        if admin_user is None:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="skip_hold_selection",
            target_type="submission",
            target_id=submission_id,
            details="",
        )

        # Очищаем кнопки текущего сообщения
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)

        # Переходим к следующему товару или в меню
        next_index = current_index + 1
        if next_index < len(forwarded_ids):
            # Есть еще товары - показываем следующий
            next_submission_id = forwarded_ids[next_index]
            next_submission = await SubmissionService(session=session).get_by_id(next_submission_id)

            if next_submission is not None:
                await state.update_data(current_forward_index=next_index)

                cap = await _render_moderation_card_caption(next_submission, session=session)
                hint = "⏱ Выбери условие холда для этого товара"
                full_caption = f"{hint}\n\n{cap}"

                # Отправляем следующий товар
                if callback.message is not None:
                    await message_answer_submission(
                        callback.message,
                        next_submission,
                        caption=full_caption,
                        reply_markup=hold_condition_keyboard(next_submission_id),
                        parse_mode="HTML",
                    )
        else:
            # Все товары обработаны - возврат в меню
            if callback.message is not None:
                await callback.message.answer("✅ Все товары обработаны!")
                await send_admin_dashboard(callback.message, session, callback.from_user.id)

            await state.clear()

        await callback.answer("⏭ Пропущено")

    except Exception as e:
        logger.error(f"Error in on_moderation_hold_skip: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
        if callback.message is not None and callback.from_user is not None:
            await send_admin_dashboard(callback.message, session, callback.from_user.id)
        await state.clear()


async def send_in_review_queue(message: Message, session: AsyncSession, admin_telegram_id: int) -> None:
    """Показывает раздел 'В работе' для указанного админа. Используется после оценки симки."""

    admin_user = await UserService(session=session).get_by_telegram_id(admin_telegram_id)
    if admin_user is None:
        return

    items, total = await SubmissionService(session=session).list_in_review_submissions_paginated(
        admin_id=admin_user.id,
        page=0,
        page_size=PAGE_SIZE,
    )

    is_chief = admin_user.role == "chief_admin"

    if not items:
        empty_msg = "У тебя нет карточек в работе." if not is_chief else "Всего нет карточек в работе."
        await send_clean_text_screen(
            trigger_message=message,
            text=empty_msg,
            key="admin:moderation:in_review",
        )
        return

    first_card = True
    for item in items:
        cap = await _render_moderation_card_caption(
            item,
            session=session,
            hint_block=HINT_IN_REVIEW if first_card else "",
        )
        first_card = False
        await message_answer_submission(
            message,
            item,
            caption=cap,
            reply_markup=moderation_review_keyboard(submission_id=item.id),
            parse_mode="HTML",
        )
    if total > PAGE_SIZE:
        await message.answer(
            "Навигация по разделу 'В работе':",
            reply_markup=pagination_keyboard(CB_MOD_IN_REVIEW_PAGE, page=0, total=total, page_size=PAGE_SIZE),
        )


@router.message(Command("in_review"))
async def on_in_review_queue(message: Message, session: AsyncSession) -> None:
    """Показывает симки, взятые админом в работу."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await message.answer("Пользователь не найден в БД.")
        return

    seller_id, category_id, date_from = _parse_filters(message.text)
    items, total = await SubmissionService(session=session).list_in_review_submissions_paginated(
        admin_id=admin_user.id,
        page=0,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    
    is_chief = admin_user.role == "chief_admin"
    
    if not items:
        empty_msg = "У тебя нет карточек в работе." if not is_chief else "Всего нет карточек в работе."
        await send_clean_text_screen(
            trigger_message=message,
            text=empty_msg,
            key="admin:moderation:in_review",
        )
        return

    first_card = True
    for item in items:
        cap = await _render_moderation_card_caption(
            item,
            session=session,
            hint_block=HINT_IN_REVIEW if first_card else "",
        )
        first_card = False
        await message_answer_submission(
            message,
            item,
            caption=cap,
            reply_markup=moderation_review_keyboard(submission_id=item.id),
            parse_mode="HTML",
        )
    if total > PAGE_SIZE:
        await message.answer(
            "Навигация по разделу 'В работе':",
            reply_markup=pagination_keyboard(CB_MOD_IN_REVIEW_PAGE, page=0, total=total, page_size=PAGE_SIZE),
        )


@router.callback_query(F.data.startswith(f"{CB_MOD_IN_REVIEW_PAGE}:"))
async def on_in_review_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None:
        await callback.answer("Админ не найден", show_alert=True)
        return
    _, _, page_raw, _ = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    items, total = await SubmissionService(session=session).list_in_review_submissions_paginated(
        admin_id=admin.id,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        first_card = True
        for item in items:
            cap = await _render_moderation_card_caption(
                item,
                session=session,
                hint_block=HINT_IN_REVIEW if page == 0 and first_card else "",
            )
            first_card = False
            await message_answer_submission(
                callback.message,
                item,
                caption=cap,
                reply_markup=moderation_review_keyboard(submission_id=item.id),
                parse_mode="HTML",
            )
        if total > PAGE_SIZE:
            await callback.message.answer(
                "Навигация:",
                reply_markup=pagination_keyboard(CB_MOD_IN_REVIEW_PAGE, page=page, total=total, page_size=PAGE_SIZE),
            )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_MOD_FORWARD_CANCEL))
async def on_forward_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Отменяет выбор чата пересылки."""

    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None and callback.from_user is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_admin_dashboard(callback.message, session, callback.from_user.id)


@router.callback_query(F.data.startswith(f"{CB_MOD_TAKE}:"))
async def on_take_to_work(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Совместимость: кнопка для одиночного товара, переводим на пачку продавца."""

    if callback.from_user is None or callback.data is None:
        return

    submission_id = int(callback.data.split(":")[2])
    submission = await session.get(Submission, submission_id)
    if submission is None:
        await callback.answer("Симка не найдена", show_alert=True)
        return

    pending_items = await SubmissionService(session=session).list_pending_submissions_by_user(
        user_id=submission.user_id
    )
    if not pending_items:
        await callback.answer("У продавца нет pending-симок", show_alert=True)
        return

    await state.set_state(AdminModerationForwardState.waiting_for_target)
    await state.update_data(
        seller_user_id=submission.user_id,
        picked_submission_ids=[submission_id],
    )

    await callback.answer()
    await bot.send_message(
        chat_id=callback.from_user.id,
        text="Выбери группу, канал или пользователя для ЛС — куда переслать этот товар:",
        reply_markup=forward_target_reply_keyboard(),
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(f"{CB_MOD_REJECT}:"))
async def on_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Отклоняет симку и уведомляет автора."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Выбери причину отклонения:",
            reply_markup=moderation_reject_template_keyboard(submission_id=submission_id),
        )


@router.callback_query(F.data.startswith(f"{CB_MOD_REJTPL}:"))
async def on_reject_template(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return
    _, _, submission_id_raw, reason_key = callback.data.split(":")
    submission_id = int(submission_id_raw)
    reasons = {
        "duplicate": (RejectionReason.DUPLICATE, "Дубликат симки"),
        "quality": (RejectionReason.QUALITY, "Низкое качество"),
        "rules": (RejectionReason.RULES_VIOLATION, "Нарушение правил"),
        "other": (RejectionReason.OTHER, "Отклонено админом"),
    }
    reason, comment = reasons.get(reason_key, (RejectionReason.OTHER, "Отклонено админом"))
    submission = await SubmissionService(session=session).reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        reason=reason,
        comment=comment,
    )
    if submission is None:
        await callback.answer("Симка уже обработана", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="reject_submission",
        target_type="submission",
        target_id=submission.id,
        details=comment,
    )
    seller = await session.get(User, submission.user_id)
    if seller is not None:
        await bot.send_message(
            chat_id=seller.telegram_id,
            text=f"Симка #{submission.id} отклонена. Причина: {comment}",
        )
    await callback.answer("Отклонено")
    if callback.message is not None:
        rejected_at = (
            submission.reviewed_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if submission.reviewed_at
            else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        current_caption = (callback.message.caption or callback.message.text or "").strip()
        updated_caption = f"❌ ОТКЛОНЕНО · {rejected_at}\n\n{current_caption}"
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(caption=updated_caption, reply_markup=None)
            else:
                await edit_message_text_safe(callback.message, updated_caption, reply_markup=None)
        except TelegramAPIError:
            await callback.message.edit_reply_markup(reply_markup=None)
        await _return_after_final_review(
            message=callback.message,
            session=session,
            telegram_id=callback.from_user.id,
            admin_id=admin_user.id,
        )


@router.callback_query(F.data.startswith(f"{CB_MOD_ACCEPT}:"))
async def on_accept(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Принимает симку, начисляет сумму и архивирует симку в архив."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
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

    submission_service = SubmissionService(session=session)
    locked = await submission_service.lock_submission(submission_id=submission_id, admin_id=admin_user.id)
    if locked is None:
        await callback.answer("⏳ Эту заявку уже взял другой админ!", show_alert=True)
        return
    settings = get_settings()
    await session.refresh(submission_obj, ["category"])
    if submission_obj.category is None and submission_obj.category_id is not None:
        submission_obj.category = await session.get(Category, submission_obj.category_id)
    archive_text = format_submission_chat_forward_title(submission_obj)
    if settings.moderation_chat_id == 0:
        await callback.answer("Не задан MODERATION_CHAT_ID в .env", show_alert=True)
        return
    archive_message = await bot_send_submission(
        bot,
        settings.moderation_chat_id,
        submission_obj,
        archive_text,
    )

    accepted = await submission_service.accept_submission(
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
        action="final_credit_submission",
        target_type="submission",
        target_id=accepted.id,
        details=f"amount={accepted.accepted_amount}",
    )

    seller = await session.get(User, accepted.user_id)
    if seller is not None:
        await bot.send_message(
            chat_id=seller.telegram_id,
            text=(f"Симка #{accepted.id}: Зачёт. Начислено: {accepted.accepted_amount} USDT."),
        )

    await callback.answer("Зачёт поставлен")
    if callback.message is not None:
        chat_label = str(settings.moderation_chat_id)
        try:
            chat_info = await bot.get_chat(settings.moderation_chat_id)
            if chat_info.title:
                chat_label = chat_info.title
            elif chat_info.username:
                chat_label = f"@{chat_info.username}"
            else:
                chat_label = "Рабочий чат"
        except TelegramAPIError:
            chat_label = "Рабочий чат"

        sent_at = accepted.reviewed_at.strftime("%Y-%m-%d %H:%M:%S UTC") if accepted.reviewed_at else "—"
        current_caption = (callback.message.caption or callback.message.text or "").strip()
        updated_caption = f"✅ ОТПРАВЛЕНО В ЧАТ: {chat_label}\n🕒 Время отправки: {sent_at}\n\n{current_caption}"
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(caption=updated_caption, reply_markup=None)
            else:
                await edit_message_text_safe(callback.message, updated_caption, reply_markup=None)
        except TelegramAPIError:
            await callback.message.edit_reply_markup(reply_markup=None)

        await _return_after_final_review(
            message=callback.message,
            session=session,
            telegram_id=callback.from_user.id,
            admin_id=admin_user.id,
        )


@router.callback_query(F.data.startswith(f"{CB_MOD_DEBIT}:"))
async def on_debit(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Финально отклоняет симку со статусом rejected (Незачёт)."""

    await _handle_final_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.REJECTED,
        reason=RejectionReason.OTHER,
        user_text="Симка получила статус: Незачёт.",
        audit_action="final_debit_submission",
    )


@router.callback_query(F.data.startswith("mod:block:"))
async def on_block(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Deprecated fallback: старый callback mod:block."""

    await _handle_final_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.BLOCKED,
        reason=RejectionReason.RULES_VIOLATION,
        user_text="Симка заблокирована (нарушение правил).",
        audit_action="deprecated_final_reject_submission",
    )


@router.callback_query(F.data.startswith("mod:notscan:"))
async def on_not_a_scan(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Deprecated fallback: старый callback mod:notscan."""

    await _handle_final_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.NOT_A_SCAN,
        reason=RejectionReason.QUALITY,
        user_text="Симка отклонена: это не скан/неподходящий формат.",
        audit_action="deprecated_final_reject_submission",
    )


def _final_reject_card_header(to_status: SubmissionStatus) -> str:
    if to_status == SubmissionStatus.REJECTED:
        return "❌ ОТКЛОНЕНО (БРАК)"
    if to_status == SubmissionStatus.BLOCKED:
        return "❌ ОТКЛОНЕНО (БЛОКИРОВКА)"
    if to_status == SubmissionStatus.NOT_A_SCAN:
        return "❌ ОТКЛОНЕНО (НЕ СКАН)"
    return "❌ ОТКЛОНЕНО"


async def _handle_final_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    to_status: SubmissionStatus,
    reason: RejectionReason,
    user_text: str,
    audit_action: str,
) -> None:
    """Общий обработчик финального отклонения."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    try:
        submission_id = int(callback.data.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    submission_service = SubmissionService(session=session)
    submission_obj = await session.get(Submission, submission_id)
    if submission_obj is None:
        await callback.answer("Симка не найдена", show_alert=True)
        return
    if submission_obj.status != SubmissionStatus.IN_REVIEW:
        await callback.answer("Симка уже обработана", show_alert=True)
        return

    locked = await submission_service.lock_submission(submission_id=submission_id, admin_id=admin_user.id)
    if locked is None:
        await callback.answer("⏳ Эту заявку уже взял другой админ!", show_alert=True)
        return

    submission = await submission_service.final_reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        to_status=to_status,
        reason=reason,
        comment=user_text,
    )
    if submission is None:
        await callback.answer("Симка уже обработана", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action=audit_action,
        target_type="submission",
        target_id=submission.id,
        details=user_text,
    )

    seller = await session.get(User, submission.user_id)
    if seller is not None:
        seller_nickname = f"@{seller.username}" if seller.username else f"@{seller.telegram_id}"
        await bot.send_message(
            chat_id=seller.telegram_id,
            text=f"Симка #{submission.id}: {user_text}\nПродавец: {seller_nickname}",
        )

    await callback.answer("Статус обновлен")
    if callback.message is not None:
        header = _final_reject_card_header(to_status)
        sent_at = (
            submission.reviewed_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if submission.reviewed_at
            else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        current_caption = (callback.message.caption or callback.message.text or "").strip()
        updated_caption = f"{header}\n🕒 Время отказа: {sent_at}\n\n{current_caption}"
        try:
            if callback.message.caption is not None:
                await callback.message.edit_caption(caption=updated_caption, reply_markup=None)
            else:
                await edit_message_text_safe(callback.message, updated_caption, reply_markup=None)
        except TelegramAPIError:
            await callback.message.edit_reply_markup(reply_markup=None)

        await _return_after_final_review(
            message=callback.message,
            session=session,
            telegram_id=callback.from_user.id,
            admin_id=admin_user.id,
        )
