from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO, StringIO

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models.enums import PayoutStatus, SubmissionStatus
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.handlers.admin_stats import send_stats_hub
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
    search_report_keyboard,
    seller_main_menu_keyboard,
)
from src.keyboards.admin_hints import (
    HINT_ADMIN_CATEGORIES,
    HINT_ARCHIVE,
    HINT_BROADCAST,
    HINT_PAYOUTS,
    HINT_REQUESTS,
)
from src.keyboards.callbacks import (
    CB_ADMIN_ARCHIVE_PAGE,
    CB_ADMIN_INWORK_HUB,
    CB_ADMIN_INWORK_OPEN,
    CB_ADMIN_INWORK_PAGE,
    CB_ADMIN_INWORK_SEARCH,
    CB_ADMIN_PAYOUTS,
    CB_ADMIN_QUEUE,
    CB_ADMIN_QUEUE_START,
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_SEARCH_PAGE,
    CB_ADMIN_STATS,
    CB_ADMIN_UNRESTRICT,
    CB_CAT,
    CB_CAT_PICK_CATEGORY,
    CB_CAT_PICK_CATEGORY_PAGE,
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_HISTORY_PAGE,
    CB_PAY_LEDGER_PAGE,
    CB_PAY_MARK,
    CB_PAY_TRASH,
    CB_PAY_TRASH_PAGE,
    CB_REQ,
    CB_REQ_CLEAR,
    CB_REQ_CLEAR_CANCEL,
    CB_REQ_CLEAR_CONFIRM,
    CB_REQ_DELETE,
    CB_REQ_FACTORY_CANCEL,
    CB_REQ_FACTORY_CONFIRM,
    CB_REQ_FACTORY_RESET,
)
from src.services import (
    AdminAuditService,
    AdminService,
    ArchiveService,
    BillingService,
    CategoryService,
    CryptoBotService,
    SellerQuotaService,
    SubmissionService,
    UserService,
)
from src.states.admin_state import AdminBroadcastState, AdminCategoryState, AdminRequestsState
from src.states.moderation_state import AdminBatchPickState, AdminInReviewLookupState, AdminModerationForwardState
from src.utils.admin_keyboard import build_admin_main_inline_keyboard, build_admin_main_menu_keyboard
from src.utils.admin_panel_text import ADMIN_PANEL_HOME_TEXT
from src.utils.submission_format import submission_status_emoji_line
from src.utils.submission_media import message_answer_submission
from src.utils.text_format import (
    edit_message_text_or_caption_safe,
    edit_message_text_safe,
    non_empty_plain,
)
from src.utils.ui_builder import GDPXRenderer

router = Router(name="admin-router")
logger = logging.getLogger(__name__)
PHONE_QUERY_PATTERN = re.compile(r"^\+7\d{10}$")
PAGE_SIZE = 5
LEDGER_PAGE_SIZE = 8
INWORK_PAGE_SIZE = 8
_ADMIN_LAST_PANEL_MSG_KEY = "admin_last_panel_message_id"


async def _admin_reply_menu(session: AsyncSession, telegram_id: int) -> ReplyKeyboardMarkup:
    """Компактная обёртка над build_admin_main_menu_keyboard (короткие строки для ruff)."""

    return await build_admin_main_menu_keyboard(session, telegram_id)


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


REQUESTS_MAX_CATEGORIES_DISPLAY = 60
CATEGORIES_PICK_PAGE_SIZE = 8


def _lock_line(submission: Submission) -> str:
    if submission.locked_by_admin is None:
        return ""
    username = submission.locked_by_admin.username or f"id:{submission.locked_by_admin.id}"
    return f"🔒 ЗАБЛОКИРОВАНО: @{escape(username)}"


def _short_phone(value: str | None) -> str:
    text = (value or "").strip() or "—"
    return text if len(text) <= 24 else f"{text[:21]}..."


def _in_work_hub_keyboard(*, items: list[Submission], page: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📱 {_short_phone(item.description_text)}",
                    callback_data=f"{CB_ADMIN_INWORK_OPEN}:{item.id}",
                )
            ]
        )
    max_page = max((total - 1) // INWORK_PAGE_SIZE, 0) if total > 0 else 0
    page = min(max(page, 0), max_page)
    if total > INWORK_PAGE_SIZE:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="<<", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
        if page < max_page:
            nav.append(InlineKeyboardButton(text=">>", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔍 Найти по номеру", callback_data=CB_ADMIN_INWORK_SEARCH)])
    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _parse_pay_uid_page(callback_data: str) -> tuple[int, int]:
    parts = callback_data.split(":")
    if len(parts) < 3:
        return 0, 0
    uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    return uid, page


def _pay_op_label(username: str) -> str:
    u = (username or "").strip() or "—"
    if len(u) > 40:
        u = u[:37] + "..."
    return f"Оплатить {u}"


async def _payout_ledger_text_and_markup(
    session: AsyncSession,
    *,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    rows = await BillingService(session=session).get_daily_report_rows()
    total = len(rows)
    max_page = max((total - 1) // LEDGER_PAGE_SIZE, 0) if total > 0 else 0
    page = min(max(page, 0), max_page)
    start = page * LEDGER_PAGE_SIZE
    chunk = rows[start : start + LEDGER_PAGE_SIZE]

    lines = ["💰 ВЕДОМОСТЬ ВЫПЛАТ", ""]
    if not rows:
        lines.append("Нет пользователей с балансом к выплате.")
    else:
        for i, r in enumerate(chunk, start=start + 1):
            lines.append(f"{i}. {r['username']} | {r['accepted_count']} шт. | {r['to_pay']} USDT")
    text = "\n".join(lines)
    kb_rows: list[list[InlineKeyboardButton]] = []
    for r in chunk:
        uid = int(r["user_id"])
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=_pay_op_label(str(r["username"])),
                    callback_data=f"{CB_PAY_MARK}:{uid}:{page}",
                )
            ]
        )
    if total > LEDGER_PAGE_SIZE:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="<<", callback_data=f"{CB_PAY_LEDGER_PAGE}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
        if page < max_page:
            nav.append(InlineKeyboardButton(text=">>", callback_data=f"{CB_PAY_LEDGER_PAGE}:{page + 1}"))
        kb_rows.append(nav)
    kb_rows.append(
        [
            InlineKeyboardButton(text="История выплат", callback_data=f"{CB_PAY_HISTORY_PAGE}:0"),
            InlineKeyboardButton(text="Корзина", callback_data=f"{CB_PAY_TRASH_PAGE}:0"),
        ]
    )
    kb_rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return text, InlineKeyboardMarkup(inline_keyboard=kb_rows)


async def _edit_payout_ledger_message(message: Message, session: AsyncSession, *, page: int) -> None:
    text, kb = await _payout_ledger_text_and_markup(session, page=page)
    await edit_message_text_safe(message, text, reply_markup=kb)


async def _payout_history_text_and_markup(session: AsyncSession, *, page: int) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.PAID,
        page=page,
        page_size=PAGE_SIZE,
    )
    max_page = max((max(total, 1) - 1) // PAGE_SIZE, 0)
    if page > max_page:
        page = max_page
        rows, total = await BillingService(session=session).get_payouts_paginated(
            status=PayoutStatus.PAID,
            page=page,
            page_size=PAGE_SIZE,
        )
    lines = ["📜 История выплат", ""]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for payout, user in rows:
            username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
            lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
    text = "\n".join(lines)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PAY_HISTORY_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_PAY_HISTORY_PAGE}:{page + 1}"))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [InlineKeyboardButton(text="💰 К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:0")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )
    return text, kb


async def _payout_trash_text_and_markup(session: AsyncSession, *, page: int) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.CANCELLED,
        page=page,
        page_size=PAGE_SIZE,
    )
    max_page = max((max(total, 1) - 1) // PAGE_SIZE, 0)
    if page > max_page:
        page = max_page
        rows, total = await BillingService(session=session).get_payouts_paginated(
            status=PayoutStatus.CANCELLED,
            page=page,
            page_size=PAGE_SIZE,
        )
    lines = ["🗑 Корзина выплат", ""]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for payout, user in rows:
            username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
            lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
    text = "\n".join(lines)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PAY_TRASH_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_PAY_TRASH_PAGE}:{page + 1}"))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [InlineKeyboardButton(text="💰 К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:0")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )
    return text, kb


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


_QUOTA_LINE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+([0-9]+(?:[.,][0-9]{1,2})?)\s*$")
_QUOTA_DELETE_RE = re.compile(r"^\s*(\d+)\s*$")


async def _format_requests_page(
    session: AsyncSession,
    *,
    page: int,
) -> tuple[str, int]:
    categories = await CategoryService(session=session).get_active_categories()
    categories = categories[:REQUESTS_MAX_CATEGORIES_DISPLAY]

    today = datetime.now(timezone.utc).date()
    quota_svc = SellerQuotaService(session=session)

    quota_rows = await quota_svc.list_quotas_for_date(today)

    total = len(categories)
    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    categories_page = categories[start_idx:end_idx]

    header = [
        "Ежедневные запросы (общие) по категориям",
        f"Дата (UTC): {today}",
        "Без привязки к продавцам",
        f"Страница: {page + 1}/{max_page + 1}",
    ]

    lines: list[str] = header + ["", "Категории (id — название):"]
    for c in categories_page:
        lines.append(f"  {c.id} — {c.title}")

    if not categories_page:
        lines.append("")
        lines.append("Активные категории не найдены.")
    lines.append("")
    lines.append("Заданные сегодня значения:")
    if not quota_rows:
        lines.append("  (пока пусто)")
    else:
        by_category: dict[int, tuple[int, Decimal, int]] = {}
        for row in quota_rows:
            cid = int(row.category_id)
            if cid in by_category:
                limit, price, cnt = by_category[cid]
                by_category[cid] = (limit, price, cnt + 1)
            else:
                by_category[cid] = (int(row.max_uploads), Decimal(row.unit_price), 1)
        for cid in sorted(by_category):
            limit, price, cnt = by_category[cid]
            lines.append(f"  category_id={cid} | лимит={limit} | цена={price} | продавцов={cnt}")

    lines.extend(
        [
            "",
            "Запрос задаётся строкой: category_id max_uploads unit_price_usdt",
            "Удаление одного: кнопка 🗑 → строка category_id",
            "Полная очистка: кнопка 🧹 (с подтверждением)",
            "Сброс до заводских: кнопка ♻️ (полная очистка всех дат)",
            "",
            HINT_REQUESTS,
        ]
    )
    return "\n".join(lines), total


def _requests_pagination_keyboard(*, page: int, total: int) -> InlineKeyboardMarkup:
    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)

    # "Разделы" клавиатуры: отдельно блок "Страницы" и отдельно блок "Поиск".
    arrows: list[InlineKeyboardButton] = []
    if page > 0:
        arrows.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_REQ}:{page - 1}"))
    arrows.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        arrows.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_REQ}:{page + 1}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Страницы", callback_data=CB_NOOP)],
            arrows,
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=CB_REQ_DELETE)],
            [InlineKeyboardButton(text="🧹 Очистить список", callback_data=CB_REQ_CLEAR)],
            [InlineKeyboardButton(text="♻️ Заводской сброс", callback_data=CB_REQ_FACTORY_RESET)],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


async def open_requests_section(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Раздел «Запросы»: ежедневные лимиты выгрузок для продавцов."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    page = 0
    text, total = await _format_requests_page(session, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total)
    await state.set_state(AdminRequestsState.waiting_for_quota_line)
    await message.answer(non_empty_plain(text), reply_markup=keyboard)


_ADMIN_FSM_STATES = (
    AdminRequestsState.waiting_for_quota_line,
    AdminRequestsState.waiting_for_delete_line,
    AdminCategoryState.waiting_for_add_title,
    AdminCategoryState.waiting_for_add_payout_rate,
    AdminCategoryState.waiting_for_add_total_limit,
    AdminCategoryState.waiting_for_add_description,
    AdminCategoryState.waiting_for_add_photo,
    AdminCategoryState.waiting_for_pick_category,
    AdminCategoryState.waiting_for_edit_value,
    AdminBroadcastState.waiting_for_text,
    AdminModerationForwardState.waiting_for_target,
    AdminModerationForwardState.waiting_for_confirm,
    AdminBatchPickState.waiting_for_submission_ids,
    AdminBatchPickState.waiting_for_action,
    AdminInReviewLookupState.waiting_for_query,
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

    tid = message.from_user.id
    st = await state.get_state()
    if st == AdminRequestsState.waiting_for_quota_line.state:
        await state.clear()
        await message.answer("Ввод запроса отменён.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st == AdminRequestsState.waiting_for_delete_line.state:
        await state.clear()
        await message.answer("Удаление запроса отменено.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st in (
        AdminCategoryState.waiting_for_add_title.state,
        AdminCategoryState.waiting_for_add_payout_rate.state,
        AdminCategoryState.waiting_for_add_total_limit.state,
        AdminCategoryState.waiting_for_add_description.state,
        AdminCategoryState.waiting_for_add_photo.state,
        AdminCategoryState.waiting_for_pick_category.state,
        AdminCategoryState.waiting_for_edit_value.state,
    ):
        await state.clear()
        await message.answer("Операция с категориями отменена.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st == AdminBroadcastState.waiting_for_text.state:
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st == AdminModerationForwardState.waiting_for_target.state:
        await state.clear()
        await message.answer("Пересылка отменена.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st == AdminModerationForwardState.waiting_for_confirm.state:
        await state.clear()
        await message.answer("Пересылка отменена.", reply_markup=await _admin_reply_menu(session, tid))
        return
    if st == AdminBatchPickState.waiting_for_submission_ids.state:
        await state.clear()
        await message.answer(
            "Выбор части пачки отменён. Снова открой «Очередь».",
            reply_markup=await _admin_reply_menu(session, tid),
        )
        return
    if st == AdminBatchPickState.waiting_for_action.state:
        await state.clear()
        await message.answer(
            "Действие для выбранной пачки отменено. Снова открой «Очередь».",
            reply_markup=await _admin_reply_menu(session, tid),
        )
        return
    if st == AdminInReviewLookupState.waiting_for_query.state:
        await state.clear()
        await message.answer("Поиск в «В работе» отменён.", reply_markup=await _admin_reply_menu(session, tid))
        return


@router.message(F.text.func(_reply_matches_menu_label("Статистика")))
async def on_admin_stats_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Сводки и отчёты."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).can_access_payout_finance(message.from_user.id):
        raise SkipHandler()

    panel_id = (await state.get_data()).get(_ADMIN_LAST_PANEL_MSG_KEY)
    await state.clear()
    if panel_id is not None:
        await state.update_data(**{_ADMIN_LAST_PANEL_MSG_KEY: panel_id})
    await send_stats_hub(message, session, state)


@router.callback_query(F.data == CB_NOOP)
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.text.func(_reply_matches_menu_label("🏃 В работе")))
@router.message(F.text.func(_reply_matches_menu_label("В работе")))
async def on_in_work_hub(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Хаб «В работе»: компактная статистика и поиск по номеру."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await message.answer("Пользователь не найден в БД.")
        return

    await _admin_delete_prev_panel_message(message, state)
    mine = await SubmissionService(session=session).get_admin_active_submissions(admin_id=admin_user.id)
    await state.clear()
    total = len(mine)
    page = 0
    if not mine:
        sent = await message.answer(
            "🏃 В работе\n\nУ вас 0 заявок в работе.",
            reply_markup=_in_work_hub_keyboard(items=[], page=0, total=0),
        )
        await _admin_store_panel_message(state, sent)
        return

    chunk = mine[:INWORK_PAGE_SIZE]
    lines = ["🏃 ВАШИ ЗАЯВКИ В РАБОТЕ:", "", "📝 ВАШИ АКТИВНЫЕ ЗАЯВКИ:"]
    base = page * INWORK_PAGE_SIZE
    for idx, item in enumerate(chunk, start=base + 1):
        seller_label = (
            f"@{item.seller.username}" if item.seller is not None and item.seller.username else f"id: {item.user_id}"
        )
        phone = (item.description_text or "").strip() or "—"
        lines.append(f"{idx}. 📱 <code>{escape(phone)}</code> | Продавец: {escape(seller_label)}")
    lines.append("")
    lines.append("Нажми на номер ниже, чтобы открыть карточку:")

    sent = await message.answer(
        "\n".join(lines),
        reply_markup=_in_work_hub_keyboard(items=chunk, page=page, total=total),
        parse_mode="HTML",
    )
    await _admin_store_panel_message(state, sent)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_PAGE}:"))
async def on_in_work_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    page = max(int(callback.data.rsplit(":", 1)[-1]), 0)
    mine = await SubmissionService(session=session).get_admin_active_submissions(admin_id=admin_user.id)
    total = len(mine)
    if not mine:
        await callback.answer()
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                "🏃 В работе\n\nУ вас 0 заявок в работе.",
                reply_markup=_in_work_hub_keyboard(items=[], page=0, total=0),
            )
        return

    max_page = max((total - 1) // INWORK_PAGE_SIZE, 0)
    page = min(page, max_page)
    chunk = mine[page * INWORK_PAGE_SIZE : page * INWORK_PAGE_SIZE + INWORK_PAGE_SIZE]
    base = page * INWORK_PAGE_SIZE
    lines = ["🏃 ВАШИ ЗАЯВКИ В РАБОТЕ:", "", "📝 ВАШИ АКТИВНЫЕ ЗАЯВКИ:"]
    for idx, item in enumerate(chunk, start=base + 1):
        seller_label = (
            f"@{item.seller.username}" if item.seller is not None and item.seller.username else f"id: {item.user_id}"
        )
        phone = (item.description_text or "").strip() or "—"
        lines.append(f"{idx}. 📱 <code>{escape(phone)}</code> | Продавец: {escape(seller_label)}")
    lines.append("")
    lines.append("Нажми на номер ниже, чтобы открыть карточку:")
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "\n".join(lines),
            reply_markup=_in_work_hub_keyboard(items=chunk, page=page, total=total),
            parse_mode="HTML",
        )


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
            reply_markup=moderation_review_keyboard(submission_id=item.id),
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
        await callback.message.answer("Введи номер для поиска в «В работе» (полный или последние цифры).")


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
            joinedload(Submission.locked_by_admin),
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


@router.callback_query(F.data.startswith(f"{CB_REQ}:"))
async def on_requests_ui(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """UI для раздела «Запросы»: пагинация и действия."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer()

    if callback.message is None:
        return

    if callback.data == CB_REQ_DELETE:
        await callback.message.edit_reply_markup(reply_markup=None)
        await state.set_state(AdminRequestsState.waiting_for_delete_line)
        await callback.message.answer(
            "Удаление запроса: отправь `category_id`.\nПример: `12`",
            parse_mode="Markdown",
        )
        return
    if callback.data == CB_REQ_CLEAR:
        await callback.message.answer(
            "Очистить весь список запросов за сегодня (UTC)?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Да, очистить", callback_data=CB_REQ_CLEAR_CONFIRM),
                        InlineKeyboardButton(text="❌ Отмена", callback_data=CB_REQ_CLEAR_CANCEL),
                    ]
                ]
            ),
        )
        return
    if callback.data == CB_REQ_CLEAR_CANCEL:
        await callback.answer("Очистка отменена")
        return
    if callback.data == CB_REQ_CLEAR_CONFIRM:
        today = datetime.now(timezone.utc).date()
        removed = await SellerQuotaService(session=session).clear_quotas_for_date(today)
        await callback.message.answer(f"Очищено записей: {removed}.")
        text, total = await _format_requests_page(session, page=0)
        keyboard = _requests_pagination_keyboard(page=0, total=total)
        await callback.message.answer(non_empty_plain(text), reply_markup=keyboard)
        await state.set_state(AdminRequestsState.waiting_for_quota_line)
        return
    if callback.data == CB_REQ_FACTORY_RESET:
        await callback.message.answer(
            "Сбросить `Запросы` до заводских настроек?\nЭто удалит все лимиты/цены по всем датам.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⚠️ Да, полный сброс",
                            callback_data=CB_REQ_FACTORY_CONFIRM,
                        ),
                        InlineKeyboardButton(text="❌ Отмена", callback_data=CB_REQ_FACTORY_CANCEL),
                    ]
                ]
            ),
        )
        return
    if callback.data == CB_REQ_FACTORY_CANCEL:
        await callback.answer("Сброс отменён")
        return
    if callback.data == CB_REQ_FACTORY_CONFIRM:
        removed_total = await SellerQuotaService(session=session).clear_all_quotas()
        await callback.message.answer(f"Заводской сброс выполнен. Удалено записей: {removed_total}.")
        text, total = await _format_requests_page(session, page=0)
        keyboard = _requests_pagination_keyboard(page=0, total=total)
        await callback.message.answer(non_empty_plain(text), reply_markup=keyboard)
        await state.set_state(AdminRequestsState.waiting_for_quota_line)
        return

    parts = callback.data.split(":", maxsplit=1)
    if len(parts) != 2:
        return
    _, page_s = parts
    try:
        page = int(page_s)
    except ValueError:
        page = 0

    text, total = await _format_requests_page(session, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total)
    await edit_message_text_safe(callback.message, text, reply_markup=keyboard)


@router.message(AdminRequestsState.waiting_for_delete_line, F.text)
async def on_requests_delete_line(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return
    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Удаление отменено.", reply_markup=await _admin_reply_menu(session, message.from_user.id))
        return
    m = _QUOTA_DELETE_RE.match(raw)
    if not m:
        await message.answer("Нужна строка: category_id. Пример: 12")
        return
    category_id = int(m.group(1))
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None:
        await message.answer("Категория с таким id не найдена.")
        return
    today = datetime.now(timezone.utc).date()
    removed = await SellerQuotaService(session=session).clear_quotas_for_category_on_date(
        category_id,
        today,
    )
    if not removed:
        await message.answer("Запрос на сегодня не найден для этой категории.")
        return
    await state.set_state(AdminRequestsState.waiting_for_quota_line)
    text, total = await _format_requests_page(session, page=0)
    keyboard = _requests_pagination_keyboard(page=0, total=total)
    await message.answer(
        f"Удалено записей по категории {category_id} («{category.title}») за {today} UTC: {removed}.",
    )
    await message.answer(non_empty_plain(text), reply_markup=keyboard)


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
    elif label == "Запросы":
        await open_requests_section(message, state, session)
    elif label == "Рассылка":
        await on_broadcast_start(message, state, session)
    elif label == "Архив (7days)":
        await on_archive_help(message, session)
    elif label == "Статистика":
        await on_admin_stats_menu(message, state, session)


@router.message(F.text == BUTTON_ENTER_ADMIN_PANEL)
async def on_enter_admin_panel(message: Message, session: AsyncSession) -> None:
    """Открывает админ-панель (reply-меню админа)."""

    if message.from_user is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(_admin_panel_intro_text(), reply_markup=await _admin_reply_menu(session, message.from_user.id))


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
    text = GDPXRenderer().render_dashboard(stats)
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
    text = GDPXRenderer().render_dashboard(stats)
    await callback.answer()
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=await build_admin_main_inline_keyboard(session, callback.from_user.id),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass


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
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await on_in_work_hub(callback.message, state, session)


@router.callback_query(F.data == CB_ADMIN_PAYOUTS)
async def on_admin_inline_payouts(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await on_daily_report(callback.message, state, session)


@router.callback_query(F.data == CB_ADMIN_STATS)
async def on_admin_inline_stats(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).can_access_payout_finance(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await on_admin_stats_menu(callback.message, state, session)


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
        await on_moderation_queue(callback.message, session)


def _admin_categories_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data=f"{CB_CAT}:add")],
            [InlineKeyboardButton(text="⛔ Отключить", callback_data=f"{CB_CAT}:disable")],
            [InlineKeyboardButton(text="✅ Включить", callback_data=f"{CB_CAT}:enable")],
            [InlineKeyboardButton(text="🧮 Лимит категории", callback_data=f"{CB_CAT}:total")],
            [InlineKeyboardButton(text="💰 Цена (USDT)", callback_data=f"{CB_CAT}:price")],
            [InlineKeyboardButton(text="📝 Описание", callback_data=f"{CB_CAT}:desc")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _admin_categories_picker_keyboard(*, categories: list, page: int) -> InlineKeyboardMarkup:
    """Инлайн-подбор категории без ввода category_id вручную."""

    total = len(categories)
    max_page = max((total - 1) // CATEGORIES_PICK_PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)
    start = page * CATEGORIES_PICK_PAGE_SIZE
    end = start + CATEGORIES_PICK_PAGE_SIZE
    cats_page = categories[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    for c in cats_page:
        state = "ACTIVE" if getattr(c, "is_active", False) else "DISABLED"
        total_limit = getattr(c, "total_upload_limit", None)
        total_limit_text = "∞" if total_limit is None else str(total_limit)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{c.id} — {c.title} | лимит: {total_limit_text} ({state})",
                    callback_data=f"{CB_CAT_PICK_CATEGORY}:{c.id}",
                )
            ]
        )

    # навигация по страницам
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_CAT_PICK_CATEGORY_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_CAT_PICK_CATEGORY_PAGE}:{page + 1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_admin_categories(session: AsyncSession) -> str:
    categories = await CategoryService(session=session).get_all_categories()
    if not categories:
        return "Категорий нет."

    lines: list[str] = ["Категории (id — название):"]
    for c in categories[:80]:
        state = "ACTIVE" if c.is_active else "DISABLED"
        total = "∞" if c.total_upload_limit is None else str(c.total_upload_limit)
        lines.append(f"{c.id}: {c.title} | {state} | цена={c.payout_rate} USDT | total={total}")
    if len(categories) > 80:
        lines.append(f"… и ещё {len(categories) - 80} категорий")
    lines.append("")
    lines.append("Управляй категориями кнопками ниже.")
    return "\n".join(lines)


@router.message(Command("admin_categories"))
async def on_admin_categories_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Меню управления категориями (подтипами операторов)."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    await state.clear()
    text = await _render_admin_categories(session)
    text = f"{text}\n\n{HINT_ADMIN_CATEGORIES}"
    await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())


@router.callback_query(F.data.startswith(f"{CB_CAT}:"))
async def on_admin_categories_actions(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обработчик кнопок управления категориями."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    if callback.message is None:
        await callback.answer("Сообщение недоступно. Отправь /admin_categories снова.", show_alert=True)
        return
    await callback.answer()

    action = callback.data.split(":", 1)[1]
    if action == "rate":
        action = "price"

    if action == "add":
        await state.clear()
        await state.set_state(AdminCategoryState.waiting_for_add_title)
        await edit_message_text_or_caption_safe(
            callback.message,
            "Добавление категории.\nПришли название категории.\nПример: МТС(Салон)\nОтмена/«Назад» — кнопкой ⬅️ Назад.",
        )
        return

    if action in ("disable", "enable", "total", "price", "desc"):
        await state.clear()
        await state.update_data(edit_action=action)
        await state.update_data(pick_page=0)
        await state.set_state(AdminCategoryState.waiting_for_pick_category)

        action_title = {
            "disable": "Отключить",
            "enable": "Включить",
            "total": "Изменить лимит категории",
            "price": "Изменить цену",
            "desc": "Изменить описание",
        }.get(action, "Действие с категорией")

        categories = await CategoryService(session=session).get_all_categories()
        keyboard = _admin_categories_picker_keyboard(categories=categories, page=0)
        await edit_message_text_or_caption_safe(
            callback.message,
            f"{action_title}.\nВыбери категорию кнопкой.",
            reply_markup=keyboard,
        )
        return

    if action.startswith("pick_page:"):
        _, page_raw = action.split(":", 1)
        try:
            page = int(page_raw)
        except ValueError:
            page = 0
        await state.update_data(pick_page=page)
        categories = await CategoryService(session=session).get_all_categories()
        keyboard = _admin_categories_picker_keyboard(categories=categories, page=page)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        return

    if action.startswith("pick:"):
        _, cat_id_raw = action.split(":", 1)
        try:
            category_id = int(cat_id_raw)
        except ValueError:
            await callback.message.answer("Некорректный category_id")
            return

        data = await state.get_data()
        edit_action = data.get("edit_action")
        if not isinstance(edit_action, str):
            await state.clear()
            await callback.message.answer("Ошибка состояния. Начни заново через /admin_categories.")
            return
        if edit_action == "rate":
            edit_action = "price"
            await state.update_data(edit_action="price")

        if edit_action == "disable":
            await CategoryService(session=session).set_active(category_id=category_id, is_active=False)
            await state.clear()
            text = await _render_admin_categories(session)
            await edit_message_text_or_caption_safe(
                callback.message,
                f"Категория отключена.\n\n{text}",
                reply_markup=_admin_categories_menu_keyboard(),
            )
            return

        if edit_action == "enable":
            await CategoryService(session=session).set_active(category_id=category_id, is_active=True)
            await state.clear()
            text = await _render_admin_categories(session)
            await edit_message_text_or_caption_safe(
                callback.message,
                f"Категория включена.\n\n{text}",
                reply_markup=_admin_categories_menu_keyboard(),
            )
            return

        if edit_action not in {"total", "price", "desc"}:
            await state.clear()
            await callback.message.answer("Неизвестное действие. Начни заново через /admin_categories.")
            return

        await state.update_data(edit_category_id=category_id)
        await state.set_state(AdminCategoryState.waiting_for_edit_value)

        if edit_action == "total":
            await edit_message_text_or_caption_safe(
                callback.message,
                "Введите <code>total_upload_limit</code> (число) или <code>-</code> для без лимита.",
                reply_markup=None,
                parse_mode="HTML",
            )
        elif edit_action == "price":
            await edit_message_text_or_caption_safe(
                callback.message,
                "Введите цену в USDT (число, например <code>100.00</code>).",
                reply_markup=None,
                parse_mode="HTML",
            )
        else:
            await edit_message_text_or_caption_safe(
                callback.message,
                "Введите новое описание. «-» — без описания.",
                reply_markup=None,
            )
        return

    logger.warning("admin_categories: неизвестное действие action=%r data=%r", action, callback.data)
    await callback.message.answer(
        "Кнопка устарела или не распознана. Отправь /admin_categories снова.",
        reply_markup=_admin_categories_menu_keyboard(),
    )


def _parse_optional_int(raw: str) -> int | None:
    """Парсит целое число, а также 'none'/'-' -> None.

    Возвращает:
    - int,
    - None (значение 'без ограничений'),
    - или None как признак ошибки не используется (ошибка будет исключением).
    """

    v = raw.strip().casefold()
    if v in {"-", "none", "null", "без", "безлимит"}:
        return None
    return int(v)


def _parse_decimal(raw: str) -> Decimal:
    """Парсит Decimal, поддерживая запятую."""

    value = raw.strip().replace(",", ".")
    return Decimal(value)


@router.message(AdminCategoryState.waiting_for_add_title, F.text)
async def on_category_add_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Добавление категории отменено.", reply_markup=kb)
        return
    if len(raw) < 2:
        await message.answer("Слишком короткое название. Попробуй ещё раз.")
        return

    await state.update_data(add_title=raw)
    await state.set_state(AdminCategoryState.waiting_for_add_payout_rate)
    await message.answer(
        "Укажи <b>цену</b> за единицу в <b>USDT</b> (число, например <code>1.50</code>).",
        parse_mode="HTML",
    )


@router.message(AdminCategoryState.waiting_for_add_payout_rate, F.text)
async def on_category_add_payout_rate(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Добавление категории отменено.", reply_markup=kb)
        return

    try:
        price = _parse_decimal(raw)
    except InvalidOperation:
        await message.answer("Неверный формат. Пример: 100.00 (USDT).")
        return

    if price <= 0:
        await message.answer("Цена должна быть больше 0.")
        return

    await state.update_data(add_price=price)
    await state.set_state(AdminCategoryState.waiting_for_add_total_limit)
    await message.answer(
        "Введите <code>total_upload_limit</code> (целое число) или <code>-</code> для без лимита.",
        parse_mode="HTML",
    )


@router.message(AdminCategoryState.waiting_for_add_total_limit, F.text)
async def on_category_add_total_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Добавление категории отменено.", reply_markup=kb)
        return

    try:
        total_limit = _parse_optional_int(raw)
    except ValueError:
        await message.answer("Неверный формат total_upload_limit. Пример: 50 или '-'.")
        return

    await state.update_data(add_total_limit=total_limit)
    await state.set_state(AdminCategoryState.waiting_for_add_description)
    await message.answer("Введите описание категории (или '-' чтобы без описания).")


@router.message(AdminCategoryState.waiting_for_add_description, F.text)
async def on_category_add_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Добавление категории отменено.", reply_markup=kb)
        return

    description: str | None = None if raw.strip() == "-" else raw
    await state.update_data(add_description=description)
    await state.set_state(AdminCategoryState.waiting_for_add_photo)
    await message.answer("Отправь фото для категории или напиши 'пропустить'.", reply_markup=None)


@router.message(AdminCategoryState.waiting_for_add_photo, F.photo)
async def on_category_add_photo_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or not message.photo:
        return

    data = await state.get_data()
    photo_file_id = message.photo[-1].file_id

    add_title = data.get("add_title")
    add_price = data.get("add_price")
    add_total_limit = data.get("add_total_limit")
    add_description = data.get("add_description")
    if add_title is None or add_price is None:
        await message.answer("Ошибка состояния. Начни добавление заново.")
        await state.clear()
        return

    await AdminService(session=session).create_category(
        title=str(add_title),
        payout_rate=add_price,
        description=add_description if add_description else None,
        photo_file_id=photo_file_id,
        total_upload_limit=add_total_limit,
    )
    await state.clear()
    await message.answer(
        "Категория добавлена.",
        reply_markup=None,
    )
    text = await _render_admin_categories(session)
    await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())


@router.message(AdminCategoryState.waiting_for_add_photo, F.text)
async def on_category_add_photo_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw == REPLY_BTN_BACK or raw.casefold() == "отмена":
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Добавление категории отменено.", reply_markup=kb)
        return

    if raw.casefold() in {"пропустить", "skip", "none", "-"}:
        data = await state.get_data()
        add_title = data.get("add_title")
        add_price = data.get("add_price")
        add_total_limit = data.get("add_total_limit")
        add_description = data.get("add_description")
        if add_title is None or add_price is None:
            await message.answer("Ошибка состояния. Начни добавление заново.")
            await state.clear()
            return

        await AdminService(session=session).create_category(
            title=str(add_title),
            payout_rate=add_price,
            description=add_description if add_description else None,
            photo_file_id=None,
            total_upload_limit=add_total_limit,
        )
        await state.clear()
        text = await _render_admin_categories(session)
        await message.answer("Категория добавлена (без фото).", reply_markup=None)
        await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())
        return

    await message.answer(
        "Похоже, это не фото и не команда. Напиши `пропустить` или отправь фото.",
        parse_mode="Markdown",
    )


@router.message(AdminCategoryState.waiting_for_edit_value, F.text)
async def on_category_edit_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        kb = await _admin_reply_menu(session, message.from_user.id)
        await message.answer("Редактирование отменено.", reply_markup=kb)
        return

    data = await state.get_data()
    edit_action = data.get("edit_action")
    category_id = data.get("edit_category_id")
    if not isinstance(edit_action, str) or not isinstance(category_id, int):
        await state.clear()
        await message.answer("Ошибка состояния. Начни заново.", reply_markup=_admin_categories_menu_keyboard())
        return
    if edit_action == "rate":
        edit_action = "price"

    result_label: str
    if edit_action == "price":
        try:
            payout_rate = _parse_decimal(raw)
        except InvalidOperation:
            await message.answer("Неверный формат. Пример: 100.00 (USDT).")
            return
        if payout_rate <= 0:
            await message.answer("Цена должна быть больше 0.")
            return
        await CategoryService(session=session).update_payout_rate(category_id=category_id, payout_rate=payout_rate)
        result_label = "Цена обновлена."

    elif edit_action == "desc":
        description: str | None = None if raw == "-" else raw
        await CategoryService(session=session).update_description(category_id=category_id, description=description)
        result_label = "Описание обновлено."

    elif edit_action == "total":
        try:
            total_limit = _parse_optional_int(raw)
        except ValueError:
            await message.answer("Неверный формат total_upload_limit. Пример: 50 или '-'.")
            return
        await CategoryService(session=session).set_total_limit(category_id=category_id, total_limit=total_limit)
        result_label = "Лимит обновлён."

    else:
        await state.clear()
        await message.answer("Неизвестное действие. Начни заново.", reply_markup=_admin_categories_menu_keyboard())
        return

    # Единый, компактный пост-экран для всех edit_action:
    # возвращаем в picker, чтобы можно было быстро править следующую категорию.
    pick_page_raw = data.get("pick_page")
    pick_page = pick_page_raw if isinstance(pick_page_raw, int) and pick_page_raw >= 0 else 0
    await state.set_state(AdminCategoryState.waiting_for_pick_category)
    categories = await CategoryService(session=session).get_all_categories()
    keyboard = _admin_categories_picker_keyboard(categories=categories, page=pick_page)
    await message.answer(f"{result_label} Выбери следующую категорию.", reply_markup=keyboard)


@router.message(F.text.func(_reply_matches_menu_label("Рассылка")))
async def on_broadcast_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Запускает массовую рассылку всем активным пользователям."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(AdminBroadcastState.waiting_for_text)
    await message.answer(f"Отправь текст рассылки одним сообщением.\n\n{HINT_BROADCAST}")


@router.message(AdminBroadcastState.waiting_for_text)
async def on_broadcast_send(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: "Bot",
) -> None:
    """Отправляет массовую рассылку и показывает статистику доставки."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст рассылки не может быть пустым. Отправь непустой текст.")
        return

    recipients = await UserService(session=session).get_all_active_users()
    delivered = 0
    failed = 0
    for user in recipients:
        try:
            await bot.send_message(chat_id=user.telegram_id, text=body)
            delivered += 1
        except TelegramAPIError:
            failed += 1

    await state.clear()
    await message.answer(
        f"Рассылка завершена.\nУспешно: {delivered}\nОшибок: {failed}",
        reply_markup=await _admin_reply_menu(session, message.from_user.id),
    )
    if admin_user is not None:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="broadcast",
            target_type="users",
            details=f"delivered={delivered},failed={failed}",
        )


@router.message(F.text.func(_reply_matches_menu_label("Запросы")))
async def on_requests_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Вход в раздел «Запросы» с главного меню."""

    await open_requests_section(message, state, session)


@router.message(AdminRequestsState.waiting_for_quota_line, F.text)
async def on_requests_quota_line(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Задаёт дневной запрос: лимит и цену за единицу."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return
    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Выход.", reply_markup=await _admin_reply_menu(session, message.from_user.id))
        return
    m = _QUOTA_LINE_RE.match(raw)
    if not m:
        await message.answer("Нужна строка: id_категории лимит цена_USDT. Пример: 12 10 1.50")
        return
    category_id = int(m.group(1))
    limit = int(m.group(2))
    price_raw = m.group(3).replace(",", ".")
    try:
        unit_price = Decimal(price_raw)
    except InvalidOperation:
        await message.answer("Цена должна быть числом, например 1.50")
        return
    if limit < 0:
        await message.answer("Лимит не может быть отрицательным.")
        return
    if unit_price < Decimal("0"):
        await message.answer("Цена не может быть отрицательной.")
        return
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None or not category.is_active:
        await message.answer("Категория с таким id не найдена или неактивна.")
        return
    today = datetime.now(timezone.utc).date()
    sellers = await UserService(session=session).list_active_sellers()
    quota_svc = SellerQuotaService(session=session)
    for seller in sellers:
        await quota_svc.upsert_quota(
            seller.id,
            category_id,
            today,
            limit,
            unit_price=unit_price,
        )
    await state.clear()
    await message.answer(
        (
            f"На {today} (UTC) по категории «{category.title}» (id {category_id}) "
            f"задан общий запрос: лимит {limit}, цена {unit_price} USDT/шт.\n"
            f"Применено к продавцам: {len(sellers)}."
        ),
        reply_markup=await _admin_reply_menu(session, message.from_user.id),
    )


@router.message(Command("daily_report"))
@router.message(F.text.func(_reply_matches_menu_label("Выплаты")))
async def on_daily_report(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Показывает итоговую ведомость к выплате (одно сообщение)."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    text, kb = await _payout_ledger_text_and_markup(session, page=0)
    body = f"{HINT_PAYOUTS}\n\n{text}"
    data = await state.get_data()
    mid = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    if mid is not None and message.chat is not None:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(mid),
                text=body,
                reply_markup=kb,
            )
            return
        except TelegramBadRequest:
            pass

    await _admin_delete_prev_panel_message(message, state)
    sent = await message.answer(body, reply_markup=kb)
    await _admin_store_panel_message(state, sent)


@router.message(F.text.func(_reply_matches_menu_label("Архив (7days)")))
async def on_archive_help(message: Message, session: AsyncSession) -> None:
    """Показывает, как искать номер в архиве за 7 дней."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(
        "Поиск в архиве 7 дней:\n"
        "/archive 1234  (последние цифры)\n"
        "/archive +79999999999  (полный номер)\n\n"
        f"{HINT_ARCHIVE}",
        reply_markup=await _admin_reply_menu(session, message.from_user.id),
    )


@router.message(Command("archive"))
async def on_archive_search(message: Message, session: AsyncSession) -> None:
    """Ищет номер в архиве товаров за 7 дней."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    query = message.text.replace("/archive", "", 1).strip()
    if not query:
        await message.answer("Формат: /archive 1234 или /archive +79999999999")
        return

    archive_service = ArchiveService(session=session)
    await archive_service.prune_expired()
    rows, total = await archive_service.search_archive_by_phone_paginated(query=query, page=0, page_size=PAGE_SIZE)
    if not rows:
        await message.answer("В архиве за 7 дней ничего не найдено.")
        return

    for submission, seller in rows:
        cap = await _render_admin_moderation_card(session=session, submission=submission)
        await message_answer_submission(
            message,
            submission,
            caption=cap,
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            parse_mode="HTML",
        )
    await message.answer(
        "Навигация архива:",
        reply_markup=pagination_keyboard(
            CB_ADMIN_ARCHIVE_PAGE,
            page=0,
            total=total,
            page_size=PAGE_SIZE,
            query=query,
        ),
    )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_ARCHIVE_PAGE}:"))
async def on_archive_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, page_raw, query = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    archive_service = ArchiveService(session=session)
    rows, total = await archive_service.search_archive_by_phone_paginated(query=query, page=page, page_size=PAGE_SIZE)
    if callback.message is not None:
        for submission, seller in rows:
            cap = await _render_admin_moderation_card(session=session, submission=submission)
            await message_answer_submission(
                callback.message,
                submission,
                caption=cap,
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
                parse_mode="HTML",
            )
        await callback.message.answer(
            "Навигация архива:",
            reply_markup=pagination_keyboard(
                CB_ADMIN_ARCHIVE_PAGE,
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=query,
            ),
        )
    await callback.answer()


@router.message(Command("s"))
async def on_search_submission(message: Message, session: AsyncSession) -> None:
    """Ищет товары в работе/истории по номеру или последним цифрам."""

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

    for submission, seller in rows:
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
        for submission, seller in rows:
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


@router.message(Command("export_report"))
async def on_export_report(message: Message, session: AsyncSession) -> None:
    """Экспортирует отчёт выплат в CSV/XLSX."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    fmt = message.text.replace("/export_report", "", 1).strip().lower() or "csv"
    rows = await BillingService(session=session).get_daily_report_rows()
    if not rows:
        await message.answer("Нет данных для экспорта.")
        return

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except Exception:
            await message.answer("Для XLSX установи зависимость openpyxl.")
            return
        wb = Workbook()
        ws = wb.active
        ws.append(["username", "accepted_count", "to_pay"])
        for row in rows:
            ws.append([str(row["username"]), int(row["accepted_count"]), str(row["to_pay"])])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        await message.answer_document(
            document=("daily_report.xlsx", buf.read()),
            caption="Экспорт XLSX готов.",
        )
        return

    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(["username", "accepted_count", "to_pay"])
    for row in rows:
        writer.writerow([row["username"], row["accepted_count"], row["to_pay"]])
    await message.answer_document(
        document=("daily_report.csv", sio.getvalue().encode("utf-8")),
        caption="Экспорт CSV готов.",
    )


@router.callback_query(F.data.startswith(f"{CB_PAY_LEDGER_PAGE}:"))
async def on_payout_ledger_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.rsplit(":", 1)[-1]), 0)
    await callback.answer()
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=page)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_MARK}:"))
async def on_mark_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    """Запрашивает подтверждение выплаты пользователю."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    if user_id <= 0:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
        await edit_message_text_safe(
            callback.message,
            f"💰 Подтверждение выплаты\n\nПользователь: {username}\nСумма к выплате: {user.pending_balance} USDT",
            reply_markup=payout_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
        )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CANCEL}:"))
async def on_mark_paid_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отменяет подтверждение выплаты и возвращает ведомость."""

    if callback.data is None:
        return
    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    await callback.answer("Оплата отменена")
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH}:"))
async def on_mark_trash(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отправляет выплату в корзину (cancelled)."""

    if callback.from_user is None or callback.data is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return
    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    payout = await BillingService(session=session).cancel_user_payout(
        user_id=user_id,
        cancelled_by_admin_id=admin_user.id,
    )
    if payout is None:
        await callback.answer("Баланс уже пустой или выплата обработана", show_alert=True)
        return
    await callback.answer("Перемещено в корзину")
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="cancel_payout",
        target_type="user",
        target_id=user_id,
        details=f"amount={payout.amount}",
    )
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CONFIRM}:"))
async def on_mark_paid_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Создает чек в CryptoBot и фиксирует выплату."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return

    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    amount = Decimal(user.pending_balance)
    if amount <= Decimal("0.00"):
        await callback.answer("Баланс к выплате уже пустой", show_alert=True)
        return

    username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
    comment = f"Payment from @GDPX1 for {username}"
    try:
        check = await CryptoBotService().create_usdt_check(amount=amount, comment=comment)
    except RuntimeError as exc:
        await callback.answer("Не удалось создать чек CryptoBot", show_alert=True)
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                f"Ошибка CryptoBot: {exc}\n\nПопробуйте снова из ведомости.",
                reply_markup=None,
            )
        return

    payout = await BillingService(session=session).mark_user_paid_with_crypto(
        user_id=user_id,
        paid_by_admin_id=admin_user.id,
        crypto_check_id=check.check_id,
        crypto_check_url=check.check_url,
        note="cryptobot_check",
    )
    if payout is None:
        await callback.answer("Выплата уже зафиксирована или баланс нулевой", show_alert=True)
        return

    await callback.answer("Выплата зафиксирована")
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="mark_paid",
        target_type="user",
        target_id=user_id,
        details=f"amount={payout.amount};check_id={check.check_id}",
    )
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)
    try:
        await bot.send_message(
            user.telegram_id,
            f"Выплата сформирована.\nСумма: {payout.amount} USDT\nПолучить чек: {check.check_url}",
        )
    except TelegramAPIError:
        pass


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_HISTORY_PAGE}:"))
async def on_payout_history_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    text, kb = await _payout_history_text_and_markup(session, page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH_PAGE}:"))
async def on_payout_trash_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    text, kb = await _payout_trash_text_and_markup(session, page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)


@router.callback_query(F.data.startswith(f"{CB_ADMIN_REPORT_SUBMISSION}:"))
async def on_submission_report(callback: CallbackQuery, session: AsyncSession) -> None:
    """Показывает детальный отчет по выбранному товару."""

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
    seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
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
    report_text = (
        f"Отчёт по товару #{submission.id}\n"
        f"Продавец: {seller_nickname}\n"
        f"Категория: {category_title}\n"
        f"📱 `{number_line}` — {category_title}\n"
        f"Текущий статус: {submission_status_emoji_line(submission.status)}\n"
        f"Создано: {submission.created_at}\n"
        f"Взято в работу: {submission.assigned_at}\n"
        f"Проверено: {submission.reviewed_at}\n"
        f"Начислено: {submission.accepted_amount}\n\n"
        "История статусов:\n"
        f"{history_text}"
    )
    if getattr(submission, "is_duplicate", False):
        report_text += "\n⚠️ ВНИМАНИЕ: ЭТОТ НОМЕР УЖЕ БЫЛ В БОТЕ РАНЕЕ!\n"
    await callback.answer()
    await callback.message.answer(non_empty_plain(report_text))  # type: ignore[union-attr]
