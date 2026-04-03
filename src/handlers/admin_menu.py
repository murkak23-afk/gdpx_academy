from __future__ import annotations

import asyncio
import csv
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO, StringIO
from typing import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.core.config import get_settings
from src.database.models.admin_audit import AdminAuditLog
from src.database.models.category import Category
from src.database.models.enums import PayoutStatus, RejectionReason, SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.handlers.admin.mailing import on_broadcast_start
from src.handlers.admin.payouts import on_daily_report
from src.handlers.moderation import on_moderation_queue
from src.keyboards import (
    BUTTON_ENTER_ADMIN_PANEL,
    BUTTON_EXIT_ADMIN_PANEL,
    CALLBACK_INLINE_BACK,
    REPLY_BTN_BACK,
    is_admin_main_menu_text,
    match_admin_menu_canonical,
    moderation_review_keyboard,
    pagination_keyboard,
    payout_confirm_keyboard,
    payout_final_confirm_keyboard,
    search_report_keyboard,
    seller_main_menu_keyboard,
)
from src.keyboards.admin_hints import (
    HINT_BROADCAST,
    HINT_PAYOUTS,
)
from src.keyboards.callbacks import (
    CB_ADMIN_BROADCAST,
    CB_ADMIN_DASHBOARD_RESET,
    CB_ADMIN_DASHBOARD_RESET_CONFIRM,
    CB_ADMIN_INWORK_BATCH_ACT,
    CB_ADMIN_INWORK_CARD_SEARCH,
    CB_ADMIN_INWORK_HUB,
    CB_ADMIN_INWORK_OPEN,
    CB_ADMIN_INWORK_PAGE,
    CB_ADMIN_INWORK_PICK_N,
    CB_ADMIN_INWORK_PICK_QTY,
    CB_ADMIN_INWORK_SEARCH,
    CB_ADMIN_INWORK_SEL_ALL,
    CB_ADMIN_INWORK_SELLER,
    CB_ADMIN_INWORK_SELLER_PAGE,
    CB_ADMIN_INWORK_TOGGLE,
    CB_ADMIN_PAYOUTS,
    CB_ADMIN_QUEUE,
    CB_ADMIN_QUEUE_START,
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_SEARCH_PAGE,
    CB_ADMIN_STATS_EXPORT_MONTH,
    CB_ADMIN_STATS_MONTH,
    CB_ADMIN_STATS_RESET,
    CB_ADMIN_STATS_RESET_CONFIRM,
    CB_ADMIN_UNRESTRICT,
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_FINAL_CONFIRM,
    CB_PAY_HISTORY_PAGE,
    CB_PAY_LEDGER_PAGE,
    CB_PAY_MARK,
    CB_PAY_PENDING_DELETE,
    CB_PAY_PENDING_PAGE,
    CB_PAY_TOPUP,
    CB_PAY_TOPUP_CHECK,
    CB_PAY_TRASH,
    CB_PAY_TRASH_PAGE,
)
from src.services import (
    AdminAuditService,
    AdminService,
    AdminStatsService,
    BillingService,
    CryptoBotService,
    SubmissionService,
    UserService,
)
from src.states.admin_state import AdminBroadcastState, AdminPayoutState, AdminSearchSimState
from src.states.moderation_state import (
    AdminBatchPickState,
    AdminCardFilterState,
    AdminInReviewLookupState,
    AdminInworkBatchState,
    AdminModerationForwardState,
)
from src.utils.admin_keyboard import build_admin_main_inline_keyboard
from src.utils.admin_panel_text import ADMIN_PANEL_HOME_TEXT
from src.utils.submission_format import format_submission_chat_forward_title, submission_status_emoji_line
from src.utils.submission_media import bot_send_submission, message_answer_submission
from src.utils.text_format import (
    edit_message_text_or_caption_safe,
    edit_message_text_safe,
    non_empty_plain,
)
from src.utils.ui_builder import GDPXRenderer

router = Router(name="admin-router")
logger = logging.getLogger(__name__)
PHONE_QUERY_PATTERN = re.compile(r"(?:\+7|7|8)\d{10}")
PAGE_SIZE = 5
LEDGER_PAGE_SIZE = 8
INWORK_PAGE_SIZE = 8
SELLERS_PAGE_SIZE = 10
SELLER_CARDS_PAGE_SIZE = 10
_ADMIN_LAST_PANEL_MSG_KEY = "admin_last_panel_message_id"
_INWORK_FILTERS_KEY = "inwork_card_queries"


async def _notify_bulk_with_progress(
    bot: Bot,
    notifications: list[tuple[int, str]],
    *,
    concurrency: int = 20,
    progress_step: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Параллельно отправляет уведомления с ограничением и прогрессом."""

    total = len(notifications)
    if total == 0:
        return 0, 0

    sem = asyncio.Semaphore(max(concurrency, 1))
    lock = asyncio.Lock()
    ok_count = 0
    fail_count = 0
    processed = 0

    async def _send_one(chat_id: int, text: str) -> None:
        nonlocal ok_count, fail_count, processed
        try:
            async with sem:
                await bot.send_message(chat_id=chat_id, text=text)
            ok = True
        except TelegramAPIError:
            ok = False

        should_report = False
        processed_now = 0
        async with lock:
            processed += 1
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            processed_now = processed
            should_report = processed_now % max(progress_step, 1) == 0 or processed_now == total

        if should_report and on_progress is not None:
            await on_progress(processed_now, total)

    await asyncio.gather(*(_send_one(chat_id, text) for chat_id, text in notifications))
    return ok_count, fail_count


def _norm_query(text: str | None) -> str:
    return (text or "").strip()


def _inwork_apply_query(items: list[Submission], query: str) -> list[Submission]:
    q = _norm_query(query)
    if not q:
        return items
    q_low = q.lower()
    q_digits = re.sub(r"\D", "", q)
    out: list[Submission] = []
    for s in items:
        phone = (s.description_text or "").strip()
        if q_low in phone.lower():
            out.append(s)
            continue
        if q_digits and q_digits in re.sub(r"\D", "", phone):
            out.append(s)
    return out


def _inwork_query_from_state(data: dict, seller_id: int) -> str:
    raw = data.get(_INWORK_FILTERS_KEY, {})
    if not isinstance(raw, dict):
        return ""
    return _norm_query(raw.get(str(seller_id)))


async def _inwork_set_query(state: FSMContext, seller_id: int, query: str) -> None:
    data = await state.get_data()
    raw = data.get(_INWORK_FILTERS_KEY, {})
    filters = dict(raw) if isinstance(raw, dict) else {}
    q = _norm_query(query)
    if q:
        filters[str(seller_id)] = q
    else:
        filters.pop(str(seller_id), None)
    await state.update_data(**{_INWORK_FILTERS_KEY: filters})


async def _delete_message_later(bot: Bot, chat_id: int, message_id: int, delay_sec: int = 20) -> None:
    """Удаляет служебное сообщение с задержкой, чтобы не захламлять чат."""

    await asyncio.sleep(delay_sec)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass


async def _admin_delete_prev_panel_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    old_id = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    if old_id is None or message.chat is None:
        return
    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=int(old_id))
    except TelegramBadRequest:
        pass


async def _admin_store_panel_message(state: FSMContext, sent: Message | None) -> None:
    if sent is None:
        return
    await state.update_data(**{_ADMIN_LAST_PANEL_MSG_KEY: sent.message_id})


def _lock_line(submission: Submission) -> str:
    return ""


def _short_phone(value: str | None) -> str:
    text = (value or "").strip() or "—"
    return text if len(text) <= 24 else f"{text[:21]}..."


# ── Группировка заявок по продавцу ──────────────────────────────────


def _group_submissions_by_seller(submissions: list[Submission]) -> list[dict]:
    """Группирует заявки по продавцу, сохраняя порядок первого появления."""
    from collections import OrderedDict

    groups: OrderedDict[int, dict] = OrderedDict()
    for sub in submissions:
        uid = sub.user_id
        if uid not in groups:
            seller = sub.seller
            if seller and seller.username:
                label = f"@{seller.username}"
            elif seller:
                label = str(seller.telegram_id)
            else:
                label = str(uid)
            groups[uid] = {
                "user_id": uid,
                "label": label,
                "count": 0,
                "submissions": [],
            }
        groups[uid]["count"] += 1
        groups[uid]["submissions"].append(sub)
    return list(groups.values())


# ── Клавиатура Level 1: список поставщиков ──────────────────────────


def _inwork_sellers_keyboard(
    *,
    seller_groups: list[dict],
    page: int,
    total_sellers: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for g in seller_groups:
        label = str(g.get("label", "—"))
        count = int(g.get("count", 0))
        btn_text = f"{label} ({count})"
        if len(btn_text) > 40:
            btn_text = f"{label[:35]}… ({count})"
        rows.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"{CB_ADMIN_INWORK_SELLER}:{g['user_id']}",
            )
        ])

    max_page = max((total_sellers - 1) // SELLERS_PAGE_SIZE, 0) if total_sellers > 0 else 0
    page = min(max(page, 0), max_page)
    if total_sellers > SELLERS_PAGE_SIZE:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
        if page < max_page:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page + 1}"))
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🔍 Поиск", callback_data=CB_ADMIN_INWORK_SEARCH),
        InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Клавиатура Level 2: карточки продавца ────────────────────────────


def _inwork_seller_cards_keyboard(
    *,
    items: list[Submission],
    seller_id: int,
    page: int,
    total: int,
    selected_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    batch_mode = selected_ids is not None
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for item in items:
        phone = (item.description_text or "").strip() or "—"
        short = phone[-5:] if len(phone) > 5 else phone
        hold_raw = (item.hold_assigned or "").strip()
        has_hold = bool(hold_raw) and hold_raw.lower() != "no_hold"
        hold_icon = " 🔒" if has_hold else ""

        if batch_mode:
            check = "✅" if item.id in selected_ids else "⬜"
            label = f"{check} ..{short}{hold_icon}"
            cb = f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:{item.id}"
        else:
            label = f"SIM: ..{short}{hold_icon}"
            cb = f"{CB_ADMIN_INWORK_OPEN}:{item.id}"

        pair.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    max_page = max((total - 1) // SELLER_CARDS_PAGE_SIZE, 0) if total > 0 else 0
    page = min(max(page, 0), max_page)
    if total > SELLER_CARDS_PAGE_SIZE:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"{CB_ADMIN_INWORK_SELLER_PAGE}:{seller_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
        if page < max_page:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"{CB_ADMIN_INWORK_SELLER_PAGE}:{seller_id}:{page + 1}"))
        rows.append(nav)

    if batch_mode:
        sel_count = len(selected_ids) if selected_ids else 0
        action_row: list[InlineKeyboardButton] = [
            InlineKeyboardButton(text="☑ Все", callback_data=f"{CB_ADMIN_INWORK_SEL_ALL}:{seller_id}"),
            InlineKeyboardButton(text="✖ Снять", callback_data=f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:0"),
        ]
        if sel_count > 0:
            action_row.append(
                InlineKeyboardButton(text=f"▶ Действие ({sel_count})", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}"),
            )
        rows.append(action_row)
        rows.append([
            InlineKeyboardButton(text="🔍 Поиск", callback_data=f"{CB_ADMIN_INWORK_CARD_SEARCH}:{seller_id}"),
            InlineKeyboardButton(text="🔢 Кол-во", callback_data=f"{CB_ADMIN_INWORK_PICK_QTY}:{seller_id}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="☐ Выбрать несколько", callback_data=f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:0"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔍 Поиск", callback_data=f"{CB_ADMIN_INWORK_CARD_SEARCH}:{seller_id}"),
        ])
    rows.append([
        InlineKeyboardButton(text="← К поставщикам", callback_data=CB_ADMIN_INWORK_HUB),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_panel_intro_text() -> str:
    return ADMIN_PANEL_HOME_TEXT


async def _fetch_admin_board_stats(session: AsyncSession) -> dict[str, int]:
    pending_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
    in_review_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW)
    approved_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.ACCEPTED)
    rejected_stmt = select(func.count(Submission.id)).where(
        Submission.status.in_(
            [
                SubmissionStatus.REJECTED,
                SubmissionStatus.BLOCKED,
                SubmissionStatus.NOT_A_SCAN,
            ]
        )
    )

    pending_count = int((await session.execute(pending_stmt)).scalar_one())
    in_review_count = int((await session.execute(in_review_stmt)).scalar_one())
    approved_count = int((await session.execute(approved_stmt)).scalar_one())
    rejected_count = int((await session.execute(rejected_stmt)).scalar_one())
    return {
        "pending_count": pending_count,
        "in_review_count": in_review_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
    }


async def _render_admin_moderation_card(
    *,
    session: AsyncSession,
    submission: Submission,
) -> str:
    svc = SubmissionService(session=session)
    is_duplicate = await svc.has_phone_duplicate(
        submission_id=submission.id,
        phone=submission.description_text,
    )
    return GDPXRenderer().render_moderation_card(submission, is_duplicate=is_duplicate)


def _admin_section_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _admin_inwork_inline_keyboard(items: list[Submission]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        phone = (item.description_text or "").strip() or "—"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📱 {phone[:18]}",
                    callback_data=f"{CB_ADMIN_INWORK_OPEN}:{item.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔍 Найти", callback_data=CB_ADMIN_INWORK_SEARCH)])
    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_payouts_inline_keyboard(rows_data: list[dict[str, int | str | Decimal]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in rows_data:
        username = str(row.get("username", "—"))
        uid = int(row["user_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💳 Оплатить {username}",
                    callback_data=f"{CB_PAY_MARK}:{uid}:0",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_queue_lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Приступить к проверке", callback_data=CB_ADMIN_QUEUE_START)],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _reply_matches_menu_label(expected: str):
    """Совпадение текста reply-кнопки с учётом регистра и пробелов."""

    def _check(t: str | None) -> bool:
        return match_admin_menu_canonical(t) == expected

    return _check


_ADMIN_FSM_STATES = (
    AdminBroadcastState.waiting_for_text,
    AdminSearchSimState.waiting_for_digits,
    AdminModerationForwardState.waiting_for_target,
    AdminModerationForwardState.waiting_for_confirm,
    AdminBatchPickState.waiting_for_submission_ids,
    AdminBatchPickState.waiting_for_action,
    AdminInReviewLookupState.waiting_for_query,
    AdminInworkBatchState.selecting,
    AdminCardFilterState.waiting_for_inwork_query,
    AdminCardFilterState.waiting_for_buffer_query,
    AdminPayoutState.waiting_for_topup_amount,
)


@router.message(F.text == REPLY_BTN_BACK, StateFilter(*_ADMIN_FSM_STATES))
async def on_admin_fsm_step_back(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Шаг назад в админских сценариях или выход в главное меню."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    st = await state.get_state()
    if st == AdminBroadcastState.waiting_for_text.state:
        await state.clear()
        await on_admin_panel(message, session)
        return
    if st == AdminSearchSimState.waiting_for_digits.state:
        await state.clear()
        await on_admin_panel(message, session)
        return
    if st == AdminModerationForwardState.waiting_for_target.state:
        await state.clear()
        pending_count = int(
            (
                await session.execute(
                    select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
                )
            ).scalar_one()
        )
        text = GDPXRenderer().render_queue_lobby(pending_count=pending_count)
        await message.answer(text, reply_markup=_admin_queue_lobby_keyboard(), parse_mode="HTML")
        return
    if st == AdminModerationForwardState.waiting_for_confirm.state:
        await state.clear()
        pending_count = int(
            (
                await session.execute(
                    select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
                )
            ).scalar_one()
        )
        text = GDPXRenderer().render_queue_lobby(pending_count=pending_count)
        await message.answer(text, reply_markup=_admin_queue_lobby_keyboard(), parse_mode="HTML")
        return
    if st == AdminBatchPickState.waiting_for_submission_ids.state:
        await state.clear()
        pending_count = int(
            (
                await session.execute(
                    select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
                )
            ).scalar_one()
        )
        text = GDPXRenderer().render_queue_lobby(pending_count=pending_count)
        await message.answer(text, reply_markup=_admin_queue_lobby_keyboard(), parse_mode="HTML")
        return
    if st == AdminBatchPickState.waiting_for_action.state:
        await state.clear()
        pending_count = int(
            (
                await session.execute(
                    select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
                )
            ).scalar_one()
        )
        text = GDPXRenderer().render_queue_lobby(pending_count=pending_count)
        await message.answer(text, reply_markup=_admin_queue_lobby_keyboard(), parse_mode="HTML")
        return
    if st == AdminInReviewLookupState.waiting_for_query.state:
        await state.clear()
        await on_in_work_hub(message, state, session)
        return
    if st == AdminInworkBatchState.selecting.state:
        await state.clear()
        await on_in_work_hub(message, state, session)
        return
    if st == AdminCardFilterState.waiting_for_inwork_query.state:
        await state.clear()
        await on_in_work_hub(message, state, session)
        return
    if st == AdminCardFilterState.waiting_for_buffer_query.state:
        await state.clear()
        await on_admin_panel(message, session)
        return
    if st == AdminPayoutState.waiting_for_topup_amount.state:
        await state.clear()
        await on_daily_report(message, state, session)
        return


@router.callback_query(F.data == CB_NOOP)
@router.callback_query(F.data == CB_NOOP)
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def on_in_work_hub(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Хаб «В работе»: Level 1 — список поставщиков."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await message.answer("Пользователь не найден в БД.")
        return

    data = await state.get_data()
    keep_filters = data.get(_INWORK_FILTERS_KEY)
    await _admin_delete_prev_panel_message(message, state)
    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=admin_user.id)
    await state.clear()
    if isinstance(keep_filters, dict):
        await state.update_data(**{_INWORK_FILTERS_KEY: keep_filters})
    groups = _group_submissions_by_seller(all_subs)
    total_sellers = len(groups)
    total_cards = len(all_subs)
    page = 0

    chunk = groups[:SELLERS_PAGE_SIZE]
    text = GDPXRenderer().render_inwork_sellers(chunk, total_sellers=total_sellers, total_cards=total_cards)
    sent = await message.answer(
        text,
        reply_markup=_inwork_sellers_keyboard(seller_groups=chunk, page=page, total_sellers=total_sellers),
        parse_mode="HTML",
    )
    await _admin_store_panel_message(state, sent)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_PAGE}:"))
async def on_in_work_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Пагинация Level 1 — список поставщиков."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    page = max(int(callback.data.rsplit(":", 1)[-1]), 0)
    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    groups = _group_submissions_by_seller(all_subs)
    total_sellers = len(groups)
    total_cards = len(all_subs)

    if not groups:
        page = 0
        chunk: list[dict] = []
    else:
        max_page = max((total_sellers - 1) // SELLERS_PAGE_SIZE, 0)
        page = min(page, max_page)
        chunk = groups[page * SELLERS_PAGE_SIZE : (page + 1) * SELLERS_PAGE_SIZE]

    text = GDPXRenderer().render_inwork_sellers(chunk, total_sellers=total_sellers, total_cards=total_cards)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=_inwork_sellers_keyboard(seller_groups=chunk, page=page, total_sellers=total_sellers),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_SELLER}:"))
async def on_inwork_seller(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Level 2 — карточки конкретного поставщика."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    current_st = await state.get_state()
    if current_st == AdminInworkBatchState.selecting.state:
        data = await state.get_data()
        await state.clear()
        keep_filters = data.get(_INWORK_FILTERS_KEY)
        if isinstance(keep_filters, dict):
            await state.update_data(**{_INWORK_FILTERS_KEY: keep_filters})

    try:
        seller_id = int(callback.data.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    total = len(seller_subs)

    if not seller_subs_full:
        await callback.answer("У этого поставщика нет карточек в работе.", show_alert=True)
        return
    if not seller_subs:
        await callback.answer("По текущему поиску карточек нет.", show_alert=True)
        return

    seller = seller_subs[0].seller
    if seller and seller.username:
        seller_label = f"@{seller.username}"
    elif seller:
        seller_label = str(seller.telegram_id)
    else:
        seller_label = str(seller_id)

    page = 0
    chunk = seller_subs[:SELLER_CARDS_PAGE_SIZE]
    text = GDPXRenderer().render_inwork_seller_cards(seller_label, chunk, total=total)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_or_caption_safe(
            callback.message,
            text,
            reply_markup=_inwork_seller_cards_keyboard(items=chunk, seller_id=seller_id, page=page, total=total),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_SELLER_PAGE}:"))
async def on_inwork_seller_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Пагинация Level 2 — карточки поставщика."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    try:
        seller_id = int(parts[2])
        page = max(int(parts[3]), 0)
    except (TypeError, ValueError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    total = len(seller_subs)

    if not seller_subs_full:
        await callback.answer("Нет карточек.", show_alert=True)
        return
    if not seller_subs:
        await callback.answer("По текущему поиску карточек нет.", show_alert=True)
        return

    seller = seller_subs_full[0].seller
    if seller and seller.username:
        seller_label = f"@{seller.username}"
    elif seller:
        seller_label = str(seller.telegram_id)
    else:
        seller_label = str(seller_id)

    max_page = max((total - 1) // SELLER_CARDS_PAGE_SIZE, 0)
    page = min(page, max_page)
    chunk = seller_subs[page * SELLER_CARDS_PAGE_SIZE : (page + 1) * SELLER_CARDS_PAGE_SIZE]

    text = GDPXRenderer().render_inwork_seller_cards(seller_label, chunk, total=total)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_or_caption_safe(
            callback.message,
            text,
            reply_markup=_inwork_seller_cards_keyboard(items=chunk, seller_id=seller_id, page=page, total=total),
            parse_mode="HTML",
        )


# ── Batch-выбор карточек ─────────────────────────────────────────


def _seller_label_from_subs(seller_subs: list[Submission], seller_id: int) -> str:
    if seller_subs:
        seller = seller_subs[0].seller
        if seller and seller.username:
            return f"@{seller.username}"
        if seller:
            return str(seller.telegram_id)
    return str(seller_id)


async def _refresh_seller_cards_screen(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    seller_id: int,
    selected_ids: set[int],
) -> None:
    """Перерисовывает экран Level 2 с текущим выделением."""
    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    total = len(seller_subs)
    if not seller_subs_full:
        await callback.answer("Нет карточек.", show_alert=True)
        return
    selected_ids &= {s.id for s in seller_subs_full}
    if not seller_subs:
        await callback.answer("По текущему поиску карточек нет.", show_alert=True)
        return
    seller_label = _seller_label_from_subs(seller_subs_full, seller_id)
    page = 0
    chunk = seller_subs[:SELLER_CARDS_PAGE_SIZE]
    text = GDPXRenderer().render_inwork_seller_cards(seller_label, chunk, total=total)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_or_caption_safe(
            callback.message,
            text,
            reply_markup=_inwork_seller_cards_keyboard(
                items=chunk, seller_id=seller_id, page=page, total=total, selected_ids=selected_ids,
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_TOGGLE}:"))
async def on_inwork_toggle(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Переключает выделение одной карточки (или входит в batch-режим)."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    seller_id = int(parts[2])
    submission_id = int(parts[3])

    data = await state.get_data()
    current_state = await state.get_state()

    if current_state == AdminInworkBatchState.selecting.state:
        selected: set[int] = set(data.get("batch_selected", []))
        batch_seller = data.get("batch_seller_id", 0)
        if batch_seller != seller_id:
            selected = set()
    else:
        selected = set()
        await state.set_state(AdminInworkBatchState.selecting)

    if submission_id == 0:
        selected.clear()
    elif submission_id in selected:
        selected.discard(submission_id)
    else:
        selected.add(submission_id)

    await state.update_data(batch_selected=list(selected), batch_seller_id=seller_id)
    await _refresh_seller_cards_screen(callback, session, state, seller_id, selected)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_SEL_ALL}:"))
async def on_inwork_select_all(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Выделить все / снять все карточки продавца."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    seller_id = int(callback.data.rsplit(":", 1)[-1])

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs = [s for s in all_subs if s.user_id == seller_id]
    all_ids = {s.id for s in seller_subs}

    data = await state.get_data()
    old_selected = set(data.get("batch_selected", []))

    if old_selected >= all_ids:
        selected: set[int] = set()
    else:
        selected = all_ids

    await state.set_state(AdminInworkBatchState.selecting)
    await state.update_data(batch_selected=list(selected), batch_seller_id=seller_id)
    await _refresh_seller_cards_screen(callback, session, state, seller_id, selected)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_CARD_SEARCH}:"))
async def on_inwork_card_search_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    seller_id = int(callback.data.rsplit(":", 1)[-1])
    await state.update_data(inwork_filter_seller_id=seller_id)
    await state.set_state(AdminCardFilterState.waiting_for_inwork_query)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_or_caption_safe(
            callback.message,
            "🔍 Введите поиск по карточкам этого поставщика.\n"
            "Можно часть номера, последние цифры или полный номер.\n\n"
            "Чтобы сбросить фильтр, отправьте: 0",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Назад", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}")],
                ]
            ),
            parse_mode="HTML",
        )


@router.message(AdminCardFilterState.waiting_for_inwork_query, F.text)
async def on_inwork_card_search_query(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    seller_id = int(data.get("inwork_filter_seller_id") or 0)
    if seller_id <= 0:
        await state.clear()
        await message.answer("Контекст поиска утерян. Откройте карточки поставщика заново.")
        return

    query = "" if message.text.strip() == "0" else message.text.strip()
    await _inwork_set_query(state, seller_id, query)
    data_after = await state.get_data()
    keep_filters = data_after.get(_INWORK_FILTERS_KEY)
    await state.clear()
    if isinstance(keep_filters, dict):
        await state.update_data(**{_INWORK_FILTERS_KEY: keep_filters})
    await on_in_work_hub(message, state, session)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_PICK_QTY}:"))
async def on_inwork_pick_qty_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    seller_id = int(callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    if callback.message is not None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="5", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:5"),
                InlineKeyboardButton(text="10", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:10"),
                InlineKeyboardButton(text="20", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:20"),
            ],
            [
                InlineKeyboardButton(text="50", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:50"),
                InlineKeyboardButton(text="Все", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:all"),
            ],
            [InlineKeyboardButton(text="← Назад", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}")],
        ])
        await edit_message_text_or_caption_safe(
            callback.message,
            "🔢 Выберите, сколько карточек выделить.\n"
            "Количество берется из полного списка карточек поставщика (с учетом текущего поиска).",
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_PICK_N}:"))
async def on_inwork_pick_n(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    seller_id = int(parts[2])
    n_raw = parts[3]

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    if not seller_subs:
        await callback.answer("Нет карточек для выделения.", show_alert=True)
        return

    if n_raw == "all":
        n = len(seller_subs)
    else:
        try:
            n = max(int(n_raw), 0)
        except (TypeError, ValueError):
            await callback.answer("Некорректное количество.", show_alert=True)
            return
    selected = {s.id for s in seller_subs[:n]}

    await state.set_state(AdminInworkBatchState.selecting)
    await state.update_data(batch_selected=list(selected), batch_seller_id=seller_id)
    await _refresh_seller_cards_screen(callback, session, state, seller_id, selected)


@router.callback_query(F.data.regexp(r"^admin:inwork_ba:\d+$"))
async def on_inwork_batch_action_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Показывает меню действий для выбранных карточек."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    seller_id = int(parts[2])
    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    if not selected:
        await callback.answer("Сначала выберите карточки.", show_alert=True)
        return

    count = len(selected)
    text = (
        f"{GDPXRenderer().render_inwork_sellers([], total_sellers=0, total_cards=0).split(chr(10))[0]}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Пакетное действие</b>\n\n"
        f"Выбрано карточек: <code>{count}</code>\n"
        f"Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◾️ ЗАЧЁТ", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:accept")],
        [
            InlineKeyboardButton(text="▫️ Не скан", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:not_scan"),
            InlineKeyboardButton(text="✕ Блок", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:blocked"),
        ],
        [InlineKeyboardButton(text="← Назад к выбору", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}")],
    ])
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^admin:inwork_ba:\d+:(accept|not_scan|blocked)$"))
async def on_inwork_batch_execute(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """Выполняет пакетное действие над выбранными карточками."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[3]

    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    if not selected:
        await callback.answer("Нет выбранных карточек.", show_alert=True)
        return
    selected_total = len(selected)

    # Сразу подтверждаем callback, чтобы не было ощущения зависания интерфейса.
    await callback.answer("⏳ Выполняю пакетную операцию...")
    progress_message: Message | None = None
    if callback.message is not None:
        progress_message = await callback.message.answer(f"⏳ Обработка: 0/{selected_total}")

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    svc = SubmissionService(session=session)
    settings = get_settings()
    ok_count = 0
    fail_count = 0

    if action in {"not_scan", "blocked"}:
        if action == "not_scan":
            to_status = SubmissionStatus.NOT_A_SCAN
            reason = RejectionReason.QUALITY
            seller_text = "❌ Симка отклонена: не скан / неподходящий формат."
            audit_action = "batch_not_scan"
        else:
            to_status = SubmissionStatus.BLOCKED
            reason = RejectionReason.RULES_VIOLATION
            seller_text = "❌ Симка заблокирована: блок на холде."
            audit_action = "batch_blocked"

        changed = await svc.final_reject_submissions_batch(
            submission_ids=list(selected),
            admin_id=admin_user.id,
            to_status=to_status,
            reason=reason,
            comment=seller_text,
        )
        ok_count = len(changed)
        fail_count = max(len(selected) - ok_count, 0)

        if progress_message is not None:
            await edit_message_text_safe(
                progress_message,
                f"⏳ Обработка в БД завершена: {ok_count}/{selected_total}. Отправляю уведомления...",
            )

        session.add(
            AdminAuditLog(
                admin_id=admin_user.id,
                action=audit_action,
                target_type="submission",
                details=f"batch_size={len(selected)};ok={ok_count};fail={fail_count}",
            )
        )

        seller_ids = {int(s.user_id) for s in changed}
        tg_by_user_id: dict[int, int] = {}
        if seller_ids:
            rows = (
                await session.execute(
                    select(User.id, User.telegram_id).where(User.id.in_(seller_ids))
                )
            ).all()
            tg_by_user_id = {int(uid): int(tg_id) for uid, tg_id in rows}

        notifications: list[tuple[int, str]] = []
        for s in changed:
            tg_id = tg_by_user_id.get(int(s.user_id))
            if tg_id is None:
                continue
            notifications.append((tg_id, f"Симка #{s.id}: {seller_text}"))

        async def _on_notify_progress(done: int, total: int) -> None:
            if progress_message is None:
                return
            await edit_message_text_safe(progress_message, f"📨 Уведомления: {done}/{total}")

        notify_ok, notify_fail = await _notify_bulk_with_progress(
            bot,
            notifications,
            concurrency=20,
            progress_step=10,
            on_progress=_on_notify_progress,
        )

        await state.clear()
        action_labels = {"accept": "✅ Зачёт", "not_scan": "❌ Не скан", "blocked": "✕ Блок"}
        summary = f"{action_labels.get(action, action)}: {ok_count} шт."
        if fail_count:
            summary += f" (пропущено: {fail_count})"
        if notifications:
            summary += f"\nУведомления: {notify_ok} ok / {notify_fail} fail"
        if callback.message is not None:
            await callback.message.answer(summary)
            from src.handlers.moderation_flow import send_in_review_queue

            await send_in_review_queue(callback.message, session, callback.from_user.id)
        if progress_message is not None:
            await edit_message_text_safe(progress_message, "✅ Пакетная операция завершена")
        return

    processed = 0
    for sub_id in selected:
        submission = await session.get(Submission, sub_id)
        if submission is None or submission.status != SubmissionStatus.IN_REVIEW:
            fail_count += 1
            processed += 1
            if progress_message is not None and (processed % 5 == 0 or processed == selected_total):
                await edit_message_text_safe(progress_message, f"⏳ Обработка: {processed}/{selected_total}")
            continue

        if action == "accept":
            await session.refresh(submission, ["category"])
            if submission.category is None and submission.category_id is not None:
                submission.category = await session.get(Category, submission.category_id)

            archive_text = format_submission_chat_forward_title(submission)
            try:
                archive_msg = await bot_send_submission(bot, settings.moderation_chat_id, submission, archive_text)
                archive_msg_id = archive_msg.message_id
            except TelegramAPIError:
                archive_msg_id = 0

            result = await svc.accept_submission(
                submission_id=sub_id,
                admin_id=admin_user.id,
                archive_chat_id=settings.moderation_chat_id,
                archive_message_id=archive_msg_id,
            )
            if result is None:
                fail_count += 1
                processed += 1
                if progress_message is not None and (processed % 5 == 0 or processed == selected_total):
                    await edit_message_text_safe(progress_message, f"⏳ Обработка: {processed}/{selected_total}")
                continue
            seller = await session.get(User, result.user_id)
            if seller:
                try:
                    await bot.send_message(
                        chat_id=seller.telegram_id,
                        text=f"✅ Симка #{result.id}: Зачёт. Начислено: {result.accepted_amount} USDT.",
                    )
                except TelegramAPIError:
                    pass
        else:
            fail_count += 1

        ok_count += 1
        processed += 1
        if progress_message is not None and (processed % 5 == 0 or processed == selected_total):
            await edit_message_text_safe(progress_message, f"⏳ Обработка: {processed}/{selected_total}")

    session.add(
        AdminAuditLog(
            admin_id=admin_user.id,
            action="batch_accept",
            target_type="submission",
            details=f"batch_size={len(selected)};ok={ok_count};fail={fail_count}",
        )
    )

    await state.clear()

    action_labels = {"accept": "✅ Зачёт", "not_scan": "❌ Не скан", "blocked": "✕ Блок"}
    summary = f"{action_labels.get(action, action)}: {ok_count} шт."
    if fail_count:
        summary += f" (пропущено: {fail_count})"

    if callback.message is not None:
        await callback.message.answer(summary)
        from src.handlers.moderation_flow import send_in_review_queue

        await send_in_review_queue(callback.message, session, callback.from_user.id)
    if progress_message is not None:
        await edit_message_text_safe(progress_message, "✅ Пакетная операция завершена")


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_OPEN}:"))
async def on_in_work_open_submission(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    try:
        submission_id = int(callback.data.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    svc = SubmissionService(session=session)
    item = await svc.get_submission_in_work_for_admin(
        submission_id=submission_id,
        admin_id=admin_user.id,
    )
    if item is None:
        await callback.answer("Эта заявка не в вашем списке «В работе».", show_alert=True)
        return

    cap = await _render_admin_moderation_card(session=session, submission=item)
    await callback.answer()
    if callback.message is not None:
        await message_answer_submission(
            callback.message,
            item,
            caption=cap,
            reply_markup=moderation_review_keyboard(
                submission_id=item.id,
                back_callback_data=f"{CB_ADMIN_INWORK_SELLER}:{item.user_id}",
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_ADMIN_INWORK_SEARCH)
async def on_in_work_search_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminInReviewLookupState.waiting_for_query)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            GDPXRenderer().render_inwork_search_prompt(),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]
                ]
            ),
            parse_mode="HTML",
        )


@router.message(AdminInReviewLookupState.waiting_for_query, F.text)
async def on_in_work_search_query(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    query = message.text.strip()
    if not query:
        await message.answer("Нужно ввести номер.")
        return

    if query.startswith("+7") and len(query) == 12:
        where_clause = Submission.description_text == query
    else:
        digits = re.sub(r"\D", "", query)
        if len(digits) < 3:
            await message.answer("Укажи минимум 3 цифры или полный номер +7XXXXXXXXXX.")
            return
        where_clause = Submission.description_text.like(f"%{digits}")

    stmt = (
        select(Submission)
        .options(
            joinedload(Submission.category),
            joinedload(Submission.seller),
        )
        .where(
            Submission.status == SubmissionStatus.IN_REVIEW,
            where_clause,
        )
        .order_by(Submission.assigned_at.desc().nullslast(), Submission.id.desc())
        .limit(10)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        await message.answer("В «В работе» ничего не найдено по этому номеру.")
        return

    for submission in rows:
        cap = await _render_admin_moderation_card(session=session, submission=submission)
        await message_answer_submission(
            message,
            submission,
            caption=cap,
            reply_markup=moderation_review_keyboard(submission_id=submission.id),
            parse_mode="HTML",
        )


@router.message(F.text.func(is_admin_main_menu_text), StateFilter(*_ADMIN_FSM_STATES))
async def on_admin_menu_interrupt_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает админский FSM при нажатии кнопки меню и выполняет выбранный раздел."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    label = match_admin_menu_canonical(message.text)
    if label is None:
        return

    data = await state.get_data()
    old_panel = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    await state.clear()
    if old_panel is not None and message.chat is not None:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=int(old_panel))
        except TelegramBadRequest:
            pass

    if label == "Очередь":
        await on_moderation_queue(message, session)
    elif label in {"В работе", "🏃 В работе"}:
        await on_in_work_hub(message, state, session)
    elif label == "Выплаты":
        await on_daily_report(message, state, session)
    elif label == "Рассылка":
        await on_broadcast_start(message, state, session)



@router.message(Command("admin"), StateFilter(*_ADMIN_FSM_STATES))
async def on_admin_command_interrupt_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает админский FSM и открывает inline-дашборд по /admin."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    data = await state.get_data()
    old_panel = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    await state.clear()
    if old_panel is not None and message.chat is not None:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=int(old_panel))
        except TelegramBadRequest:
            pass

    await on_admin_panel(message, session)


@router.message(F.text == BUTTON_ENTER_ADMIN_PANEL)
async def on_enter_admin_panel(message: Message, session: AsyncSession) -> None:
    """Открывает инлайн-панель админа (убирает reply-клавиатуру)."""

    if message.from_user is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    # Убираем reply-клавиатуру с экрана пользователя
    await message.answer("\u2060", reply_markup=ReplyKeyboardRemove())
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = message.from_user.username or str(message.from_user.id)
    text = GDPXRenderer().render_admin_dashboard(stats)
    await message.answer(
        text,
        reply_markup=await build_admin_main_inline_keyboard(session, message.from_user.id),
        parse_mode="HTML",
    )


@router.message(F.text == BUTTON_EXIT_ADMIN_PANEL)
async def on_exit_admin_panel(message: Message, session: AsyncSession) -> None:
    """Возвращает обычное меню селлера + кнопку входа в админ-панель."""

    if message.from_user is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден в БД.")
        return
    await message.answer(
        "Вы вышли из админ-панели. Профиль и сделки — в обычном меню ниже.",
        reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
    )


@router.message(Command("admin"))
@router.message(Command("a"))
async def on_admin_panel(message: Message, session: AsyncSession) -> None:
    """Открывает главное меню админа."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    await message.answer("\u2060", reply_markup=ReplyKeyboardRemove())
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = message.from_user.username or str(message.from_user.id)
    text = GDPXRenderer().render_admin_dashboard(stats)
    await message.answer(
        text,
        reply_markup=await build_admin_main_inline_keyboard(session, message.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CALLBACK_INLINE_BACK)
async def on_back_to_admin_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    await state.clear()
    stats = await _fetch_admin_board_stats(session)
    stats["username"] = callback.from_user.username or str(callback.from_user.id)
    text = GDPXRenderer().render_admin_dashboard(stats)
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=await build_admin_main_inline_keyboard(session, callback.from_user.id),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            await callback.message.answer(
                text=text,
                reply_markup=await build_admin_main_inline_keyboard(session, callback.from_user.id),
                parse_mode="HTML",
            )


@router.callback_query(F.data == CB_ADMIN_QUEUE)
async def on_admin_inline_queue(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    pending_count = int(
        (
            await session.execute(
                select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
            )
        ).scalar_one()
    )
    text = GDPXRenderer().render_queue_lobby(pending_count=pending_count)
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=_admin_queue_lobby_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == CB_ADMIN_INWORK_HUB)
async def on_admin_inline_inwork(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Level 1 — список поставщиков (вход из dashboard / кнопка «К поставщикам»)."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    await state.clear()
    groups = _group_submissions_by_seller(all_subs)
    total_sellers = len(groups)
    total_cards = len(all_subs)

    chunk = groups[:SELLERS_PAGE_SIZE]
    text = GDPXRenderer().render_inwork_sellers(chunk, total_sellers=total_sellers, total_cards=total_cards)
    markup = _inwork_sellers_keyboard(seller_groups=chunk, page=0, total_sellers=total_sellers)

    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == CB_ADMIN_PAYOUTS)
async def on_admin_inline_payouts(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await on_daily_report(callback.message, state, session, _caller_id=callback.from_user.id)


@router.callback_query(F.data == CB_ADMIN_QUEUE_START)
async def on_admin_queue_start(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await on_moderation_queue(callback.message, session, _caller_id=callback.from_user.id)


