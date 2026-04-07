"""Admin «В работе» (in-work) hub — handlers for CB_ADMIN_INWORK_* family.

Handles everything related to the admin's personal in-work queue:
  - Level 1: seller list with pagination & batch-select
  - Level 2: individual cards per seller
  - Batch accept / not_scan / blocked actions with progress display
  - Card search within in-work list

Also owns ``send_in_review_queue`` (shared utility called from moderation
and grading handlers after completing a review action) and the
``/in_review`` command handler.
"""

from __future__ import annotations

from loguru import logger
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.core.config import get_settings
from src.database.models.admin_audit import AdminAuditLog
from src.database.models.category import Category
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User
from src.keyboards import CALLBACK_INLINE_BACK, REPLY_BTN_BACK, moderation_review_keyboard
from src.keyboards.callbacks import (
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
    CB_MOD_IN_REVIEW_PAGE,
    CB_NOOP,
)
from src.keyboards.callback_data import SellerMatCardCB
from src.services import AdminAuditService, AdminService, SubmissionService, UserService
from src.states.moderation_state import (
    AdminCardFilterState,
    AdminInReviewLookupState,
    AdminInworkBatchState,
)
from src.utils.admin_keyboard import send_admin_dashboard
from src.utils.moderation_card import render_admin_moderation_card
from src.utils.notify import notify_bulk_with_progress
from src.utils.submission_format import format_submission_chat_forward_title
from src.utils.submission_media import bot_send_submission, message_answer_submission
from src.utils.text_format import edit_message_text_or_caption_safe, edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

router = Router(name="admin-inwork-router")

INWORK_PAGE_SIZE = 8
SELLERS_PAGE_SIZE = 10
SELLER_CARDS_PAGE_SIZE = 10

_ADMIN_LAST_PANEL_MSG_KEY = "admin_last_panel_message_id"
_INWORK_FILTERS_KEY = "inwork_card_queries"


# ── Private helpers ──────────────────────────────────────────────────────────────


def _seller_asset_detail_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="ПОСМОТРЕТЬ ДЕТАЛИ", callback_data=SellerMatCardCB(submission_id=submission_id))
    return b.as_markup()


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


async def _admin_delete_prev_panel_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    old_id = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    if old_id is None or message.chat is None:
        return
    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=int(old_id))  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass


async def _admin_store_panel_message(state: FSMContext, sent: Message | None) -> None:
    if sent is None:
        return
    await state.update_data(**{_ADMIN_LAST_PANEL_MSG_KEY: sent.message_id})


def _short_phone(value: str | None) -> str:
    text = (value or "").strip() or "—"
    return text if len(text) <= 24 else f"{text[:21]}..."


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


def _inwork_sellers_keyboard(
    *,
    seller_groups: list[dict],
    page: int,
    total_sellers: int,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    widths: list[int] = []
    for g in seller_groups:
        label = str(g.get("label", "—"))
        count = int(g.get("count", 0))
        btn_text = f"{label} ({count})"
        if len(btn_text) > 40:
            btn_text = f"{label[:35]}… ({count})"
        b.button(text=btn_text, callback_data=f"{CB_ADMIN_INWORK_SELLER}:{g['user_id']}")
        widths.append(1)

    max_page = max((total_sellers - 1) // SELLERS_PAGE_SIZE, 0) if total_sellers > 0 else 0
    page = min(max(page, 0), max_page)
    if total_sellers > SELLERS_PAGE_SIZE:
        nav_count = 0
        if page > 0:
            b.button(text="◀", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page - 1}")
            nav_count += 1
        b.button(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP)
        nav_count += 1
        if page < max_page:
            b.button(text="▶", callback_data=f"{CB_ADMIN_INWORK_PAGE}:{page + 1}")
            nav_count += 1
        widths.append(nav_count)
    b.button(text="🔍 Поиск", callback_data=CB_ADMIN_INWORK_SEARCH)
    b.button(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)
    widths.append(2)
    b.adjust(*widths)
    return b.as_markup()


def _inwork_seller_cards_keyboard(
    *,
    items: list[Submission],
    seller_id: int,
    page: int,
    total: int,
    selected_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    batch_mode = selected_ids is not None
    b = InlineKeyboardBuilder()
    widths: list[int] = []
    pair_count = 0
    for item in items:
        phone = (item.description_text or "").strip() or "—"
        short = phone[-5:] if len(phone) > 5 else phone
        hold_raw = (item.hold_assigned or "").strip()
        has_hold = bool(hold_raw) and hold_raw.lower() != "no_hold"
        hold_icon = " 🔒" if has_hold else ""

        if batch_mode:
            check = "✅" if item.id in selected_ids else "⬜"  # type: ignore[operator]
            label = f"{check} ..{short}{hold_icon}"
            cb = f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:{item.id}"
        else:
            label = f"SIM: ..{short}{hold_icon}"
            cb = f"{CB_ADMIN_INWORK_OPEN}:{item.id}"

        b.button(text=label, callback_data=cb)
        pair_count += 1
        if pair_count % 2 == 0:
            widths.append(2)
    if pair_count % 2 == 1:
        widths.append(1)

    max_page = max((total - 1) // SELLER_CARDS_PAGE_SIZE, 0) if total > 0 else 0
    page = min(max(page, 0), max_page)
    if total > SELLER_CARDS_PAGE_SIZE:
        nav_count = 0
        if page > 0:
            b.button(text="◀", callback_data=f"{CB_ADMIN_INWORK_SELLER_PAGE}:{seller_id}:{page - 1}")
            nav_count += 1
        b.button(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP)
        nav_count += 1
        if page < max_page:
            b.button(text="▶", callback_data=f"{CB_ADMIN_INWORK_SELLER_PAGE}:{seller_id}:{page + 1}")
            nav_count += 1
        widths.append(nav_count)

    if batch_mode:
        sel_count = len(selected_ids) if selected_ids else 0
        b.button(text="☑ Все", callback_data=f"{CB_ADMIN_INWORK_SEL_ALL}:{seller_id}")
        b.button(text="✖ Снять", callback_data=f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:0")
        if sel_count > 0:
            b.button(text=f"▶ Действие ({sel_count})", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}")
            widths.append(3)
        else:
            widths.append(2)
        b.button(text="🔍 Поиск", callback_data=f"{CB_ADMIN_INWORK_CARD_SEARCH}:{seller_id}")
        b.button(text="🔢 Кол-во", callback_data=f"{CB_ADMIN_INWORK_PICK_QTY}:{seller_id}")
        widths.append(2)
    else:
        b.button(text="☐ Выбрать несколько", callback_data=f"{CB_ADMIN_INWORK_TOGGLE}:{seller_id}:0")
        widths.append(1)
        b.button(text="🔍 Поиск", callback_data=f"{CB_ADMIN_INWORK_CARD_SEARCH}:{seller_id}")
        widths.append(1)
    b.button(text="← К поставщикам", callback_data=CB_ADMIN_INWORK_HUB)
    widths.append(1)
    b.adjust(*widths)
    return b.as_markup()


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
        await callback.answer("НЕТ КАРТОЧЕК.", show_alert=True)
        return
    selected_ids &= {s.id for s in seller_subs_full}
    if not seller_subs:
        await callback.answer("ПО ТЕКУЩЕМУ ПОИСКУ КАРТОЧЕК НЕТ.", show_alert=True)
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


# ── Public: send in-review queue (shared with grading / moderation) ──────────


async def send_in_review_queue(message: Message, session: AsyncSession, admin_telegram_id: int) -> None:
    """Хаб «В работе» после оценки — Level 1: список поставщиков.

    Используется из admin_grading.py и moderation handlers после завершения
    ревью — показывает обновлённый список карточек «В работе».
    """
    admin_user = await UserService(session=session).get_by_telegram_id(admin_telegram_id)
    if admin_user is None:
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=admin_user.id)
    groups = _group_submissions_by_seller(all_subs)
    total_sellers = len(groups)
    total_cards = len(all_subs)

    chunk = groups[:SELLERS_PAGE_SIZE]
    text = GDPXRenderer().render_inwork_sellers(chunk, total_sellers=total_sellers, total_cards=total_cards)

    if not all_subs:
        await message.answer(text, parse_mode="HTML")
        return

    await message.answer(
        text,
        reply_markup=_inwork_sellers_keyboard(seller_groups=chunk, page=0, total_sellers=total_sellers),
        parse_mode="HTML",
    )


# ── Public: main entry point (called by menu_core FSM-back handler) ──────────


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


# ── Handlers ─────────────────────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_INWORK_HUB)
async def on_admin_inline_inwork(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Level 1 — список поставщиков (вход из dashboard / кнопка «К поставщикам»)."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
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


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_PAGE}:"))
async def on_in_work_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Пагинация Level 1 — список поставщиков."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
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
        await callback.answer("НЕКОРРЕКТНЫЕ ДАННЫЕ.", show_alert=True)
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    total = len(seller_subs)

    if not seller_subs_full:
        await callback.answer("У ЭТОГО ПОСТАВЩИКА НЕТ КАРТОЧЕК В РАБОТЕ.", show_alert=True)
        return
    if not seller_subs:
        await callback.answer("ПО ТЕКУЩЕМУ ПОИСКУ КАРТОЧЕК НЕТ.", show_alert=True)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("НЕКОРРЕКТНЫЕ ДАННЫЕ.", show_alert=True)
        return
    try:
        seller_id = int(parts[2])
        page = max(int(parts[3]), 0)
    except (TypeError, ValueError):
        await callback.answer("НЕКОРРЕКТНЫЕ ДАННЫЕ.", show_alert=True)
        return

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    total = len(seller_subs)

    if not seller_subs_full:
        await callback.answer("НЕТ КАРТОЧЕК.", show_alert=True)
        return
    if not seller_subs:
        await callback.answer("ПО ТЕКУЩЕМУ ПОИСКУ КАРТОЧЕК НЕТ.", show_alert=True)
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


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_TOGGLE}:"))
async def on_inwork_toggle(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Переключает выделение одной карточки (или входит в batch-режим)."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("ОШИБКА", show_alert=True)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
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
            reply_markup=(
                InlineKeyboardBuilder().button(
                    text="◀ Назад", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}"
                ).as_markup()
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    seller_id = int(callback.data.rsplit(":", 1)[-1])
    await callback.answer()
    if callback.message is not None:
        b_qty = InlineKeyboardBuilder()
        b_qty.button(text="5", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:5")
        b_qty.button(text="10", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:10")
        b_qty.button(text="20", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:20")
        b_qty.button(text="50", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:50")
        b_qty.button(text="Все", callback_data=f"{CB_ADMIN_INWORK_PICK_N}:{seller_id}:all")
        b_qty.button(text="◀ Назад", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}")
        b_qty.adjust(3, 2, 1)
        kb = b_qty.as_markup()
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("ОШИБКА", show_alert=True)
        return
    seller_id = int(parts[2])
    n_raw = parts[3]

    all_subs = await SubmissionService(session=session).get_admin_active_submissions(admin_id=0)
    seller_subs_full = [s for s in all_subs if s.user_id == seller_id]
    data = await state.get_data()
    query = _inwork_query_from_state(data, seller_id)
    seller_subs = _inwork_apply_query(seller_subs_full, query)
    if not seller_subs:
        await callback.answer("НЕТ КАРТОЧЕК ДЛЯ ВЫДЕЛЕНИЯ.", show_alert=True)
        return

    if n_raw == "all":
        n = len(seller_subs)
    else:
        try:
            n = max(int(n_raw), 0)
        except (TypeError, ValueError):
            await callback.answer("НЕКОРРЕКТНОЕ КОЛИЧЕСТВО.", show_alert=True)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("НЕКОРРЕКТНЫЕ ДАННЫЕ", show_alert=True)
        return
    seller_id = int(parts[2])
    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    if not selected:
        await callback.answer("СНАЧАЛА ВЫБЕРИТЕ КАРТОЧКИ.", show_alert=True)
        return

    count = len(selected)
    text = (
        f"{GDPXRenderer().render_inwork_sellers([], total_sellers=0, total_cards=0).split(chr(10))[0]}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Пакетное действие</b>\n\n"
        f"Выбрано карточек: <code>{count}</code>\n"
        f"Выберите действие:"
    )
    b_batch = InlineKeyboardBuilder()
    b_batch.button(text="◾️ ЗАЧЁТ", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:accept")
    b_batch.button(text="▫️ НЕ СКАН", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:not_scan")
    b_batch.button(text="✕ БЛОК", callback_data=f"{CB_ADMIN_INWORK_BATCH_ACT}:{seller_id}:blocked")
    b_batch.button(text="◀ НАЗАД К ВЫБОРУ", callback_data=f"{CB_ADMIN_INWORK_SELLER}:{seller_id}")
    b_batch.adjust(1, 2, 1)
    kb = b_batch.as_markup()
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^admin:inwork_ba:\d+:(accept|not_scan|blocked)$"))
async def on_inwork_batch_execute(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    """Выполняет пакетное действие над выбранными карточками."""
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[3]

    data = await state.get_data()
    selected = set(data.get("batch_selected", []))
    if not selected:
        await callback.answer("НЕТ ВЫБРАННЫХ КАРТОЧЕК.", show_alert=True)
        return
    selected_total = len(selected)

    await callback.answer("⏳ ВЫПОЛНЯЮ ПАКЕТНУЮ ОПЕРАЦИЮ...")
    progress_message: Message | None = None
    if callback.message is not None:
        progress_message = await callback.message.answer(f"⏳ ОБРАБОТКА: 0/{selected_total}")

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("ПОЛЬЗОВАТЕЛЬ НЕ НАЙДЕН В БД", show_alert=True)
        return

    svc = SubmissionService(session=session)
    settings = get_settings()
    ok_count = 0
    fail_count = 0

    if action in {"not_scan", "blocked"}:
        if action == "not_scan":
            to_status = SubmissionStatus.NOT_A_SCAN
            reason = RejectionReason.QUALITY
            seller_text = "❌ СИМКА ОТКЛОНЕНА: НЕ СКАН / НЕПОДХОДЯЩИЙ ФОРМАТ."
            audit_action = "batch_not_scan"
        else:
            to_status = SubmissionStatus.BLOCKED
            reason = RejectionReason.RULES_VIOLATION
            seller_text = "❌ СИМКА ЗАБЛОКИРОВАНА: БЛОК НА ХОЛДЕ."
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
                f"⏳ ОБРАБОТКА В БД ЗАВЕРШЕНА: {ok_count}/{selected_total}. ОТПРАВЛЯЮ УВЕДОМЛЕНИЯ...",
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

        notifications: list[tuple[int, str, InlineKeyboardMarkup | None]] = []
        for s in changed:
            tg_id = tg_by_user_id.get(int(s.user_id))
            if tg_id is None:
                continue
            notifications.append(
                (
                    tg_id,
                    f"СИМКА #{s.id}: {seller_text}",
                    _seller_asset_detail_keyboard(s.id),
                )
            )

        async def _on_notify_progress(done: int, total: int) -> None:
            if progress_message is None:
                return
            await edit_message_text_safe(progress_message, f"📨 УВЕДОМЛЕНИЯ: {done}/{total}")

        notify_ok, notify_fail = await notify_bulk_with_progress(
            bot,
            notifications,
            concurrency=20,
            progress_step=10,
            on_progress=_on_notify_progress,
        )

        await state.clear()
        action_labels = {"accept": "✅ ЗАЧЁТ", "not_scan": "❌ НЕ СКАН", "blocked": "✕ БЛОК"}
        summary = f"{action_labels.get(action, action)}: {ok_count} ШТ."
        if fail_count:
            summary += f" (ПРОПУЩЕНО: {fail_count})"
        if notifications:
            summary += f"\nУВЕДОМЛЕНИЯ: {notify_ok} OK / {notify_fail} FAIL"
        if callback.message is not None:
            await callback.message.answer(summary)
            await send_in_review_queue(callback.message, session, callback.from_user.id)
        if progress_message is not None:
            await edit_message_text_safe(progress_message, "✅ ПАКЕТНАЯ ОПЕРАЦИЯ ЗАВЕРШЕНА")
        return

    processed = 0
    for sub_id in selected:
        submission = await session.get(Submission, sub_id)
        if submission is None or submission.status != SubmissionStatus.IN_REVIEW:
            fail_count += 1
            processed += 1
            if progress_message is not None and (processed % 5 == 0 or processed == selected_total):
                await edit_message_text_safe(progress_message, f"⏳ ОБРАБОТКА: {processed}/{selected_total}")
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
                    await edit_message_text_safe(progress_message, f"⏳ ОБРАБОТКА: {processed}/{selected_total}")
                continue
            seller = await session.get(User, result.user_id)
            if seller:
                try:
                    await bot.send_message(
                        chat_id=seller.telegram_id,
                        text=f"✅ СИМКА #{result.id}: ЗАЧЁТ. НАЧИСЛЕНО: {result.accepted_amount} USDT.",
                        reply_markup=_seller_asset_detail_keyboard(result.id),
                    )
                except TelegramAPIError:
                    pass
        else:
            fail_count += 1

        ok_count += 1
        processed += 1
        if progress_message is not None and (processed % 5 == 0 or processed == selected_total):
            await edit_message_text_safe(progress_message, f"⏳ ОБРАБОТКА: {processed}/{selected_total}")

    session.add(
        AdminAuditLog(
            admin_id=admin_user.id,
            action="batch_accept",
            target_type="submission",
            details=f"batch_size={len(selected)};ok={ok_count};fail={fail_count}",
        )
    )

    await state.clear()

    action_labels = {"accept": "✅ ЗАЧЁТ", "not_scan": "❌ НЕ СКАН", "blocked": "✕ БЛОК"}
    summary = f"{action_labels.get(action, action)}: {ok_count} ШТ."
    if fail_count:
        summary += f" (ПРОПУЩЕНО: {fail_count})"

    if callback.message is not None:
        await callback.message.answer(summary)
        await send_in_review_queue(callback.message, session, callback.from_user.id)
    if progress_message is not None:
        await edit_message_text_safe(progress_message, "✅ ПАКЕТНАЯ ОПЕРАЦИЯ ЗАВЕРШЕНА")


@router.callback_query(F.data.startswith(f"{CB_ADMIN_INWORK_OPEN}:"))
async def on_in_work_open_submission(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("ПОЛЬЗОВАТЕЛЬ НЕ НАЙДЕН В БД", show_alert=True)
        return

    try:
        submission_id = int(callback.data.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        await callback.answer("НЕКОРРЕКТНЫЕ ДАННЫЕ КНОПКИ.", show_alert=True)
        return

    svc = SubmissionService(session=session)
    item = await svc.get_submission_in_work_for_admin(
        submission_id=submission_id,
        admin_id=admin_user.id,
    )
    if item is None:
        await callback.answer("ЭТА ЗАЯВКА НЕ В ВАШЕМ СПИСКЕ «В РАБОТЕ».", show_alert=True)
        return

    cap = await render_admin_moderation_card(session=session, submission=item)
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
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    await state.set_state(AdminInReviewLookupState.waiting_for_query)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            GDPXRenderer().render_inwork_search_prompt(),
            reply_markup=(
                InlineKeyboardBuilder().button(
                    text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK
                ).as_markup()
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
        await message.answer("НУЖНО ВВЕСТИ НОМЕР.")
        return

    if query.startswith("+7") and len(query) == 12:
        where_clause = Submission.description_text == query
    else:
        digits = re.sub(r"\D", "", query)
        if len(digits) < 3:
            await message.answer("УКАЖИ МИНИМУМ 3 ЦИФРЫ ИЛИ ПОЛНЫЙ НОМЕР +7XXXXXXXXXX.")
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
        await message.answer("В «В РАБОТЕ» НИЧЕГО НЕ НАЙДЕНО ПО ЭТОМУ НОМЕРУ.")
        return

    for submission in rows:
        cap = await render_admin_moderation_card(session=session, submission=submission)
        await message_answer_submission(
            message,
            submission,
            caption=cap,
            reply_markup=moderation_review_keyboard(submission_id=submission.id),
            parse_mode="HTML",
        )


# ── /in_review command + in_review_page (re-owned from moderation_flow) ──────


@router.message(Command("in_review"))
async def on_in_review_queue(message: Message, session: AsyncSession) -> None:
    """Показывает симки в работе — компактный хаб."""
    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await send_in_review_queue(message, session, message.from_user.id)


@router.callback_query(F.data.startswith(f"{CB_MOD_IN_REVIEW_PAGE}:"))
async def on_in_review_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """Пагинация in_review — показывает компактный хаб."""
    if callback.from_user is None or callback.data is None:
        return
    await callback.answer()
    if callback.message is not None:
        await send_in_review_queue(callback.message, session, callback.from_user.id)
